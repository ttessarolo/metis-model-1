import { createHash } from 'node:crypto';
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
    metis_revision?: string;
    metis_tree?: string;
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

type RuntimeIdentity = {
    node: string;
    node_path: string;
    tsx_path: string;
    runner_path: string;
    snapshot_revision: string;
    snapshot_tree: string;
    tooling_package_sha256: string;
    tooling_lock_sha256: string;
    node_modules_sha256: string;
    node_binary_sha256: string;
    sandbox_exec_path: string;
    sandbox_policy_version: string;
    sandbox_policy_sha256: string;
};

function argument(argv: string[], name: string): string {
    const index = argv.indexOf(name);
    if (index < 0 || !argv[index + 1]) throw new Error(`${name} is required`);
    return argv[index + 1];
}

function parseIdentity(root: string, revision: string, tree: string, packageSha: string, lockSha: string, modulesSha: string, runnerSha: string, nodeBinarySha: string, sandboxPolicyVersion: string, sandboxPolicySha: string): void {
    const identity = JSON.parse(readFileSync(path.join(root, '.metis-oracle-identity.json'), 'utf8')) as Record<string, unknown>;
    if (identity.revision !== revision || identity.tree !== tree
        || identity.package_sha256 !== packageSha || identity.lock_sha256 !== lockSha
        || identity.node_modules_sha256 !== modulesSha || identity.runner_sha256 !== runnerSha
        || identity.node_binary_sha256 !== nodeBinarySha
        || identity.sandbox_exec_path !== 'sandbox-exec:///usr/bin/sandbox-exec'
        || identity.sandbox_policy_version !== sandboxPolicyVersion
        || identity.sandbox_policy_sha256 !== sandboxPolicySha) {
        throw new Error('isolated Metis snapshot identity does not match its validated pins');
    }
}

function invalid(
    request: Request,
    toolchain: { revision: string; tree: string },
    diagnostics: { parser: Json[]; link: Json[]; validation: Json[]; all: Json[] },
    ast: Json[],
    failure: { kind: string; message: string },
    runtime: RuntimeIdentity,
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
    const allowed = new Set(['schema_version', 'source', 'filename', 'endpoint', 'metis_root', 'metis_revision', 'metis_tree', 'workspace_sources']);
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
    const metisRoot = argument(argv, '--metis-root');
    const revision = argument(argv, '--metis-revision');
    const tree = argument(argv, '--metis-tree');
    const packageSha = argument(argv, '--tooling-package-sha256');
    const lockSha = argument(argv, '--tooling-lock-sha256');
    const modulesSha = argument(argv, '--node-modules-sha256');
    const runnerSha = argument(argv, '--runner-sha256');
    const nodeBinarySha = argument(argv, '--node-binary-sha256');
    const sandboxPolicyVersion = argument(argv, '--sandbox-policy-version');
    const sandboxPolicySha = argument(argv, '--sandbox-policy-sha256');
    const snapshotIdentity = argument(argv, '--snapshot-identity');
    const runtimeNodePath = argument(argv, '--runtime-node-path');
    const nodeActualPath = argument(argv, '--node-actual-path');
    const runtimeTsxPath = argument(argv, '--runtime-tsx-path');
    const runtimeRunnerPath = argument(argv, '--runtime-runner-path');
    const runnerActualPath = argument(argv, '--runner-actual-path');
    const tsxPath = argument(argv, '--tsx-path');
    if (path.isAbsolute(metisRoot) === false || path.isAbsolute(tsxPath) === false) throw new Error('strict Metis root and tsx path are required');
    if (snapshotIdentity !== `snapshot://${revision}/${tree}`) throw new Error('snapshot identity does not match revision and tree');
    if (request.metis_revision !== undefined && request.metis_revision !== revision) throw new Error('request revision does not match snapshot');
    if (request.metis_tree !== undefined && request.metis_tree !== tree) throw new Error('request tree does not match snapshot');
    parseIdentity(metisRoot, revision, tree, packageSha, lockSha, modulesSha, runnerSha, nodeBinarySha, sandboxPolicyVersion, sandboxPolicySha);
    if (nodeBinarySha !== '5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c'
        || sandboxPolicyVersion !== '1'
        || sandboxPolicySha !== 'ee5178deb85dee0799f1042397133c362211fa1d6e302ffcf9b82e68cb035540') throw new Error('isolated runtime policy does not match its validated pin');
    if (path.resolve(process.execPath) !== path.resolve(nodeActualPath)) throw new Error('node runtime path does not match the validated identity');
    if (path.resolve(process.argv[1] ?? '') !== path.resolve(runnerActualPath)) throw new Error('runner path does not match the validated identity');
    if (!path.resolve(tsxPath).startsWith(`${path.resolve(metisRoot)}${path.sep}`)) throw new Error('tsx path is outside the isolated snapshot');
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
    const runtime: RuntimeIdentity = {
        node: process.version,
        node_path: runtimeNodePath,
        tsx_path: runtimeTsxPath,
        runner_path: runtimeRunnerPath,
        snapshot_revision: revision,
        snapshot_tree: tree,
        tooling_package_sha256: `sha256:${packageSha}`,
        tooling_lock_sha256: `sha256:${lockSha}`,
        node_modules_sha256: `sha256:${modulesSha}`,
        node_binary_sha256: `sha256:${nodeBinarySha}`,
        sandbox_exec_path: 'sandbox-exec:///usr/bin/sandbox-exec',
        sandbox_policy_version: '1',
        sandbox_policy_sha256: 'sha256:ee5178deb85dee0799f1042397133c362211fa1d6e302ffcf9b82e68cb035540',
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
