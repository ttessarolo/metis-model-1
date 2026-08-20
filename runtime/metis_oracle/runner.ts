import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

const SCHEMA_VERSION = 1;
const LANGUAGE_VERSION = '0.43';

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type Request = {
    schema_version: number;
    source: string;
    filename: string;
    endpoint: string | null;
    metis_root?: string;
    workspace_sources?: { filename: string; source: string }[];
};

function canonical(value: unknown): string {
    if (value === null || typeof value !== 'object') return JSON.stringify(value);
    if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${canonical(object[key])}`).join(',')}}`;
}

function sha(value: unknown): string {
    return `sha256:${createHash('sha256').update(canonical(value)).digest('hex')}`;
}

function jsonSafe(value: unknown, seen = new WeakSet<object>()): Json {
    if (value === null || typeof value === 'string' || typeof value === 'boolean') {
        return value;
    }
    if (typeof value === 'number') {
        if (!Number.isFinite(value)) throw new Error('non-finite number in oracle evidence');
        return value;
    }
    if (typeof value === 'bigint') return String(value);
    if (typeof value !== 'object') return String(value);
    if (seen.has(value)) return '[cycle]';
    seen.add(value);
    try {
        if (Array.isArray(value)) return value.map((item) => jsonSafe(item, seen));
        if (value instanceof Map) {
            return [...value.entries()].sort(([a], [b]) => String(a).localeCompare(String(b)))
                .map(([key, item]) => [String(key), jsonSafe(item, seen)]);
        }
        const object = value as Record<string, unknown>;
        const result: { [key: string]: Json } = {};
        for (const key of Object.keys(object).sort()) {
            if (key === '$container' || key === '$document' || key === '$cstNode' || key === 'ref') continue;
            result[key] = jsonSafe(object[key], seen);
        }
        return result;
    } finally {
        seen.delete(value);
    }
}

function astNodes(root: unknown): Record<string, unknown>[] {
    const nodes: Record<string, unknown>[] = [];
    const seen = new WeakSet<object>();
    const walk = (value: unknown): void => {
        if (!value || typeof value !== 'object') return;
        if (seen.has(value)) return;
        seen.add(value);
        if (!Array.isArray(value) && typeof (value as { $type?: unknown }).$type === 'string') {
            nodes.push(value as Record<string, unknown>);
        }
        if (Array.isArray(value)) value.forEach(walk);
        else for (const [key, child] of Object.entries(value)) {
            if (!key.startsWith('$') && key !== 'ref') walk(child);
        }
    };
    walk(root);
    return nodes;
}

function diagnostic(value: unknown, filename: string): Json {
    const item = value as { message?: unknown; severity?: unknown; code?: unknown; range?: unknown };
    return jsonSafe({
        filename,
        message: String(item.message ?? value),
        severity: item.severity ?? null,
        code: item.code ?? null,
        range: item.range ?? null,
    });
}

function isLinkDiagnostic(value: Json): boolean {
    const code = String((value as { code?: unknown }).code ?? '').toLowerCase();
    if (code.includes('link')) return true;
    const message = String((value as { message?: unknown }).message ?? '').toLowerCase();
    return ['cannot resolve reference', 'could not resolve reference', 'unresolved reference', 'reference not found', 'impossibile risolvere il riferimento'].some((marker) => message.includes(marker));
}

function validFilename(filename: unknown): filename is string {
    return typeof filename === 'string'
        && filename.endsWith('.metis')
        && !path.isAbsolute(filename)
        && !filename.split(/[\\/]/).includes('..');
}

function unsupportedEntries(value: unknown, prefix = '$'): string[] {
    if (!value || typeof value !== 'object') return [];
    if (Array.isArray(value)) {
        return value.flatMap((item, index) => unsupportedEntries(item, `${prefix}[${index}]`));
    }
    const object = value as Record<string, unknown>;
    const own = Array.isArray(object.unsupported) && object.unsupported.length > 0
        ? [`${prefix}.unsupported`]
        : [];
    return own.concat(Object.entries(object).flatMap(([key, item]) => unsupportedEntries(item, `${prefix}.${key}`)));
}

function git(root: string, ...args: string[]): string {
    return execFileSync('git', ['-C', root, ...args], { encoding: 'utf8' }).trim();
}

function invalid(
    request: Request,
    toolchain: { revision: string; tree: string },
    diagnostics: { parser: Json[]; link: Json[]; validation: Json[]; all: Json[] },
    ast: Json[],
    failure: { kind: string; message: string },
    runtime: { node: string; node_path: string; runner_path: string },
): Record<string, Json> {
    return {
        schema_version: SCHEMA_VERSION,
        status: 'invalid',
        endpoint: { name: request.endpoint, count: 0 },
        diagnostics,
        ast: { inventory: ast, signature: sha(ast) },
        ir: { value: null, signature: null },
        toolchain: { revision: toolchain.revision, tree: toolchain.tree, language_version: LANGUAGE_VERSION },
        runtime,
        failure,
    };
}

async function main(): Promise<void> {
    const raw = readFileSync(0, 'utf8');
    let parsed: unknown;
    try { parsed = JSON.parse(raw); } catch { throw new Error('request is malformed JSON'); }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('request must be an object');
    const request = parsed as Request;
    const allowed = new Set(['schema_version', 'source', 'filename', 'endpoint', 'metis_root', 'workspace_sources']);
    if (Object.keys(request).some((key) => !allowed.has(key))) throw new Error('request contains unknown fields');
    if (request.schema_version !== SCHEMA_VERSION || typeof request.source !== 'string' || !request.source) throw new Error('request contract is invalid');
    if (!validFilename(request.filename)) throw new Error('filename is invalid');
    if (request.endpoint !== null && request.endpoint !== undefined && (typeof request.endpoint !== 'string' || !request.endpoint)) throw new Error('endpoint is invalid');
    const workspace = request.workspace_sources ?? [];
    if (!Array.isArray(workspace) || workspace.length > 512) throw new Error('workspace_sources is invalid');
    const workspaceNames = new Set<string>();
    for (const item of workspace) {
        if (!item || typeof item !== 'object' || Object.keys(item).sort().join(',') !== 'filename,source'
            || !validFilename(item.filename) || typeof item.source !== 'string' || !item.source
            || item.filename === request.filename || workspaceNames.has(item.filename)) {
            throw new Error('workspace source is invalid or duplicated');
        }
        workspaceNames.add(item.filename);
    }
    const argv = process.argv.slice(2);
    const rootArg = argv.indexOf('--metis-root');
    const metisRoot = rootArg >= 0 ? argv[rootArg + 1] : request.metis_root;
    if (!metisRoot || path.isAbsolute(metisRoot) === false) throw new Error('strict metis root is required');
    const revision = git(metisRoot, 'rev-parse', 'HEAD');
    const tree = git(metisRoot, 'rev-parse', 'HEAD^{tree}');
    const tooling = path.join(metisRoot, 'tooling');
    const langiumUrl = pathToFileURL(path.join(tooling, 'node_modules/langium/lib/index.js')).href;
    const servicesModule = await import(pathToFileURL(path.join(tooling, 'src/language/metis-module.ts')).href);
    const compileModule = await import(pathToFileURL(path.join(tooling, 'src/compiler/compile.ts')).href);
    const serializeModule = await import(pathToFileURL(path.join(tooling, 'src/compiler/serialize.ts')).href);
    const langium = await import(langiumUrl);
    const { shared } = servicesModule.createMetisServices(langium.EmptyFileSystem);
    const factory = shared.workspace.LangiumDocumentFactory;
    const documents = [...workspace, { filename: request.filename, source: request.source }]
        .sort((a, b) => a.filename.localeCompare(b.filename))
        .map((item) => {
            const uri = langium.URI.file(path.join('/metis-oracle', item.filename));
            const document = factory.fromString(item.source, uri);
            shared.workspace.LangiumDocuments.addDocument(document);
            return { filename: item.filename, document };
        });
    await shared.workspace.DocumentBuilder.build(documents.map((item) => item.document), { validation: true });
    const candidate = documents.find((item) => item.filename === request.filename);
    if (!candidate) throw new Error('candidate document is missing');
    const parser = documents.flatMap(({ filename, document }) =>
        (document.parseResult?.parserErrors ?? []).map((item: unknown) => diagnostic(item, filename)));
    const all = documents.flatMap(({ filename, document }) =>
        (document.diagnostics ?? []).map((item: unknown) => diagnostic(item, filename)));
    const link = all.filter(isLinkDiagnostic);
    const validation = all.filter((item) => !isLinkDiagnostic(item));
    const diagnostics = { parser, link, validation, all };
    const model = candidate.document.parseResult?.value;
    const inventory = jsonSafe(model);
    const endpoints = astNodes(model).filter((node) => node.$type === 'Endpoint');
    const runtime = {
        node: process.version,
        node_path: path.resolve(process.execPath),
        runner_path: path.resolve(process.argv[1] ?? ''),
    };
    const toolchain = { revision, tree };
    if (parser.length > 0) {
        process.stdout.write(canonical(invalid(request, toolchain, diagnostics, inventory, { kind: 'parse', message: 'parser diagnostics present' }, runtime)));
        return;
    }
    const selected = request.endpoint
        ? endpoints.filter((node) => node.name === request.endpoint)
        : endpoints;
    if (selected.length !== 1) {
        const ambiguous = invalid(request, toolchain, diagnostics, inventory, {
            kind: selected.length === 0 ? 'endpoint_missing' : 'endpoint_ambiguous',
            message: `expected exactly one selected endpoint, found ${selected.length}`,
        }, runtime);
        ambiguous.endpoint = { name: request.endpoint ?? null, count: selected.length };
        process.stdout.write(canonical(ambiguous));
        return;
    }
    const endpointNode = selected[0];
    const endpointName = typeof endpointNode.name === 'string' ? endpointNode.name : null;
    const endpoint = { name: endpointName, count: selected.length };
    if (link.length > 0 || validation.some((item) => Number((item as { severity?: unknown }).severity) === 1)) {
        process.stdout.write(canonical({ ...invalid(request, toolchain, diagnostics, inventory, { kind: link.length > 0 ? 'link' : 'validation', message: 'diagnostics prevent compilation' }, runtime), endpoint }));
        return;
    }
    let ir: unknown;
    try {
        const compiled = compileModule.compileEndpoint(endpointNode, request.filename);
        ir = JSON.parse(serializeModule.serializeIr(compiled));
    } catch (error) {
        process.stdout.write(canonical({ ...invalid(request, toolchain, diagnostics, inventory, { kind: 'compile', message: String(error) }, runtime), endpoint }));
        return;
    }
    const unsupported = unsupportedEntries(ir);
    if (unsupported.length > 0) {
        process.stdout.write(canonical({ ...invalid(request, toolchain, diagnostics, inventory, {
            kind: 'unsupported', message: `compiled IR contains unsupported nodes at ${unsupported.join(',')}`,
        }, runtime), endpoint }));
        return;
    }
    const safeIr = jsonSafe(ir);
    process.stdout.write(canonical({
        schema_version: SCHEMA_VERSION,
        status: 'ok',
        endpoint,
        diagnostics,
        ast: { inventory, signature: sha(inventory) },
        ir: { value: safeIr, signature: sha(safeIr) },
        toolchain: { revision, tree, language_version: LANGUAGE_VERSION },
        runtime,
        failure: null,
    }));
}

main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 2;
});
