/**
 * Read-only Metis Brain runner.
 *
 * Python materializes an immutable session snapshot in a private temporary
 * directory and executes this file inside the pinned Metis archive sandbox.
 * The runner never writes a tenant or opens the network. Source text is emitted
 * only inside the bounded lossless receipt returned to its Python caller.
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { stream, type LangiumDocuments } from '../../tooling/node_modules/langium/lib/index.js';
import {
  buildRuntimeCtx,
  compileTenantEndpoints,
  loadTenantDocs,
  tenantErrors,
} from '../../tooling/src/compiler/tenant-build.js';
import { tenantIdFromMetisToml } from '../../tooling/src/compiler/tenant-artifact-set.js';
import {
  describeTenant,
  valuesForField,
  type FieldSkeleton,
  type TenantContext,
} from '../../tooling/src/cli/catalog-domain.js';
import { catalogThresholds } from '../../tooling/src/language/field-values.js';

type CompileRequest = {
  schema_version: 1;
  operation: 'compile';
  tenant_root: string;
  endpoint: string | null;
};

type CatalogRequest = {
  schema_version: 1;
  operation: 'semantic-catalog';
  tenant_root: string;
};

type LosslessInventoryRequest = {
  schema_version: 1;
  operation: 'lossless-inventory';
  tenant_root: string;
  relative_path: string;
  endpoint: string;
};

type LosslessApplyRequest = {
  schema_version: 1;
  operation: 'lossless-apply';
  tenant_root: string;
  relative_path: string;
  endpoint: string;
  plan: unknown;
};

type Request = CompileRequest | CatalogRequest | LosslessInventoryRequest | LosslessApplyRequest;

function fail(message: string): never {
  throw new Error(message);
}

function exactObject(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return fail('request must be an object');
  }
  return value as Record<string, unknown>;
}

async function readRequest(): Promise<Request> {
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const raw of process.stdin) {
    const chunk = Buffer.from(raw as Uint8Array);
    bytes += chunk.length;
    if (bytes > 256 * 1024) { return fail('request exceeds the byte limit'); }
    chunks.push(chunk);
  }
  const value = exactObject(JSON.parse(Buffer.concat(chunks).toString('utf8')));
  if (value.schema_version !== 1 || ![
    'compile',
    'semantic-catalog',
    'lossless-inventory',
    'lossless-apply',
  ].includes(String(value.operation))) {
    return fail('request identity is invalid');
  }
  const tenantRoot = value.tenant_root;
  if (typeof tenantRoot !== 'string' || !path.isAbsolute(tenantRoot) || tenantRoot.includes('\0')) {
    return fail('tenant root is invalid');
  }
  if (value.operation === 'semantic-catalog') {
    if (Object.keys(value).sort().join(',') !== 'operation,schema_version,tenant_root') {
      return fail('catalog request has an invalid field roster');
    }
    return { schema_version: 1, operation: 'semantic-catalog', tenant_root: tenantRoot };
  }
  if (value.operation === 'lossless-inventory' || value.operation === 'lossless-apply') {
    const expected = value.operation === 'lossless-inventory'
      ? 'endpoint,operation,relative_path,schema_version,tenant_root'
      : 'endpoint,operation,plan,relative_path,schema_version,tenant_root';
    if (Object.keys(value).sort().join(',') !== expected) {
      return fail('lossless request has an invalid field roster');
    }
    const relativePath = value.relative_path;
    const endpoint = value.endpoint;
    if (
      typeof relativePath !== 'string'
      || !relativePath.endsWith('.metis')
      || relativePath.includes('\\')
      || relativePath.includes('\0')
      || relativePath.split('/').some((part) => !part || part === '.' || part === '..' || part === '.git')
    ) {
      return fail('lossless relative path is invalid');
    }
    if (typeof endpoint !== 'string' || endpoint.length === 0 || endpoint.length > 256) {
      return fail('lossless endpoint is invalid');
    }
    if (value.operation === 'lossless-inventory') {
      return {
        schema_version: 1,
        operation: 'lossless-inventory',
        tenant_root: tenantRoot,
        relative_path: relativePath,
        endpoint,
      };
    }
    return {
      schema_version: 1,
      operation: 'lossless-apply',
      tenant_root: tenantRoot,
      relative_path: relativePath,
      endpoint,
      plan: value.plan,
    };
  }
  if (Object.keys(value).sort().join(',') !== 'endpoint,operation,schema_version,tenant_root') {
    return fail('compile request has an invalid field roster');
  }
  const endpoint = value.endpoint;
  if (endpoint !== null && typeof endpoint !== 'string') {
    return fail('endpoint is invalid');
  }
  if (typeof endpoint === 'string' && (endpoint.length === 0 || endpoint.length > 256)) {
    return fail('endpoint is invalid');
  }
  return { schema_version: 1, operation: 'compile', tenant_root: tenantRoot, endpoint };
}

function tenantSourcePath(tenantRoot: string, relativePath: string): string {
  const root = fs.realpathSync(tenantRoot);
  const candidate = path.resolve(root, ...relativePath.split('/'));
  const prefix = root.endsWith(path.sep) ? root : `${root}${path.sep}`;
  if (!candidate.startsWith(prefix)) { return fail('lossless target escapes the tenant'); }
  const status = fs.lstatSync(candidate);
  if (!status.isFile() || status.isSymbolicLink()) { return fail('lossless target is not a regular file'); }
  const resolved = fs.realpathSync(candidate);
  if (!resolved.startsWith(prefix)) { return fail('lossless target resolves outside the tenant'); }
  return resolved;
}

function exactNode(
  inventory: {
    nodes: Array<{
      id: string;
      type: string;
      span: { offset: number; end: number; byteOffset: number; byteEnd: number };
      preimageSha256: string;
    }>;
  },
  node: { $type?: unknown; $cstNode?: { offset: number; end: number } },
): {
  id: string;
  type: string;
  span: { offset: number; end: number; byteOffset: number; byteEnd: number };
  preimageSha256: string;
} {
  const type = node.$type;
  const cst = node.$cstNode;
  if (typeof type !== 'string' || cst === undefined) { return fail('lossless AST target has no CST identity'); }
  const matches = inventory.nodes.filter((item) => (
    item.type === type && item.span.offset === cst.offset && item.span.end === cst.end
  ));
  if (matches.length !== 1) { return fail('lossless AST target does not map uniquely to inventory'); }
  return matches[0]!;
}

async function losslessInventory(
  tenantRoot: string,
  relativePath: string,
  requestedEndpoint: string,
): Promise<Record<string, unknown>> {
  const sourcePath = tenantSourcePath(tenantRoot, relativePath);
  const source = fs.readFileSync(sourcePath);
  const { buildInventory } = await import('../../tooling/src/lossless/inventory.js');
  const result = buildInventory(source);
  if (!result.ok) {
    return {
      schema_version: 1,
      operation: 'lossless-inventory',
      status: 'rejected',
      relative_path: relativePath,
      endpoint: requestedEndpoint,
      inventory: null,
      target: null,
      reasons: result.reasons,
    };
  }
  const docs = await loadTenantDocs(tenantRoot, { validate: false });
  const targetDocs = docs.filter((doc) => fs.realpathSync(doc.uri.fsPath) === sourcePath);
  if (targetDocs.length !== 1) { return fail('lossless target document is not unique'); }
  const model = targetDocs[0]!.parseResult.value as {
    elements?: Array<{
      $type?: unknown;
      $cstNode?: { offset: number; end: number };
      name?: unknown;
      members?: Array<{
        $type?: unknown;
        $cstNode?: { offset: number; end: number };
        count?: unknown;
        page?: unknown;
        pageDefault?: unknown;
        clauses?: Array<{ $type?: unknown; $cstNode?: { offset: number; end: number } }>;
      }>;
    }>;
  };
  const endpoints = (model.elements ?? []).filter((item) => (
    item.$type === 'Endpoint' && item.name === requestedEndpoint
  ));
  if (endpoints.length !== 1) { return fail('lossless endpoint is not unique in target document'); }
  const endpoint = endpoints[0]!;
  const takes = (endpoint.members ?? []).filter((item) => item.$type === 'Take');
  if (takes.length !== 1) { return fail('lossless endpoint does not have one direct take'); }
  const take = takes[0]!;
  const includes = (take.clauses ?? []).filter((item) => item.$type === 'IncludeClause');
  if (includes.length !== 1) { return fail('lossless take does not have one direct include clause'); }
  const include = includes[0]!;
  const endpointNode = exactNode(result.inventory, endpoint);
  const takeNode = exactNode(result.inventory, take);
  const includeNode = exactNode(result.inventory, include);
  const takeShape = take.page === true
    ? { mode: 'page', value: typeof take.pageDefault === 'number' ? take.pageDefault : null }
    : { mode: 'count', value: typeof take.count === 'number' ? take.count : null };
  if (takeShape.value !== null && (!Number.isSafeInteger(takeShape.value) || takeShape.value <= 0)) {
    return fail('lossless take shape is invalid');
  }
  return {
    schema_version: 1,
    operation: 'lossless-inventory',
    status: 'ok',
    relative_path: relativePath,
    endpoint: requestedEndpoint,
    inventory: result.inventory,
    target: {
      endpoint_node_id: endpointNode.id,
      take_node_id: takeNode.id,
      take_preimage_sha256: takeNode.preimageSha256,
      take_span: takeNode.span,
      take_shape: takeShape,
      include_node_id: includeNode.id,
      include_preimage_sha256: includeNode.preimageSha256,
      include_span: includeNode.span,
    },
    reasons: [],
  };
}

async function losslessApply(
  tenantRoot: string,
  relativePath: string,
  requestedEndpoint: string,
  plan: unknown,
): Promise<Record<string, unknown>> {
  const sourcePath = tenantSourcePath(tenantRoot, relativePath);
  const source = fs.readFileSync(sourcePath);
  const { applyEditPlan } = await import('../../tooling/src/lossless/apply.js');
  const receipt = await applyEditPlan(source, plan, {
    compileProof: 'validate',
    tenantDir: tenantRoot,
    sourcePath,
  });
  return {
    schema_version: 1,
    operation: 'lossless-apply',
    status: receipt.outcome === 'APPLIED' ? 'ok' : 'rejected',
    relative_path: relativePath,
    endpoint: requestedEndpoint,
    proof_mode: 'validate',
    receipt,
  };
}

async function context(tenantRoot: string): Promise<TenantContext> {
  const metisToml = fs.readFileSync(path.join(tenantRoot, 'metis.toml'), 'utf8');
  const tenant = tenantIdFromMetisToml(metisToml);
  const docs = await loadTenantDocs(tenantRoot, { validate: false });
  const langiumDocs = { all: stream(docs) } as unknown as LangiumDocuments;
  return {
    docs,
    langiumDocs,
    thresholds: catalogThresholds(langiumDocs),
    tenant,
    tenantDir: tenantRoot,
  };
}

function finiteFields(fields: FieldSkeleton[], parent?: string): string[] {
  const result: string[] = [];
  for (const field of fields) {
    const fieldPath = parent === undefined ? field.name : `${parent}.${field.name}`;
    if (['inline', 'list', 'enum'].includes(field.domain.kind) && (field.domain.size ?? 0) > 0) {
      result.push(fieldPath);
    }
    if (field.fields) { result.push(...finiteFields(field.fields, fieldPath)); }
  }
  return result;
}

async function semanticCatalog(tenantRoot: string): Promise<Record<string, unknown>> {
  const ctx = await context(tenantRoot);
  const describe = describeTenant(ctx, undefined, { semantic: true });
  const values = [];
  for (const catalog of describe.catalogs) {
    for (const field of finiteFields(catalog.fields)) {
      values.push(valuesForField(ctx, catalog.name, field, { semantic: true }));
    }
  }
  return {
    schema_version: 1,
    operation: 'semantic-catalog',
    describe,
    values,
    counts: {
      catalogs: describe.catalogs.length,
      finite_fields: values.length,
      values: values.reduce((total, item) => total + (item.values?.length ?? 0), 0),
    },
  };
}

function sha256(text: string): string {
  return `sha256:${createHash('sha256').update(text, 'utf8').digest('hex')}`;
}

async function compile(tenantRoot: string, requestedEndpoint: string | null): Promise<Record<string, unknown>> {
  const docs = await loadTenantDocs(tenantRoot, { validate: false });
  const diagnostics = tenantErrors(docs).slice(0, 128);
  if (diagnostics.length > 0) {
    return {
      schema_version: 1,
      operation: 'compile',
      status: 'invalid',
      diagnostics,
      endpoint: null,
      endpoint_sha256: null,
      runtime_context_sha256: null,
    };
  }
  const compiled = compileTenantEndpoints(docs, tenantRoot);
  const names = [...compiled.keys()].sort();
  let selected: string | null = null;
  if (requestedEndpoint !== null) {
    const matches = names.filter((name) => name === requestedEndpoint || name.endsWith(`.${requestedEndpoint}`));
    if (matches.length !== 1) {
      return {
        schema_version: 1,
        operation: 'compile',
        status: 'invalid',
        diagnostics: [{
          file: '',
          line: 1,
          code: 'BRAIN_ENDPOINT_IDENTITY',
          message: matches.length === 0 ? 'endpoint richiesto non compilato' : 'endpoint richiesto ambiguo',
        }],
        endpoint: null,
        endpoint_sha256: null,
        runtime_context_sha256: null,
      };
    }
    selected = matches[0];
  }
  const endpointSource = selected === null ? null : compiled.get(selected) ?? null;
  const runtimeContext = JSON.stringify(buildRuntimeCtx(docs, tenantRoot));
  return {
    schema_version: 1,
    operation: 'compile',
    status: 'ok',
    diagnostics: [],
    endpoint: selected,
    endpoint_sha256: endpointSource === null ? null : sha256(endpointSource),
    runtime_context_sha256: sha256(runtimeContext),
  };
}

async function main(): Promise<void> {
  const request = await readRequest();
  const response = request.operation === 'semantic-catalog'
    ? await semanticCatalog(request.tenant_root)
    : request.operation === 'compile'
      ? await compile(request.tenant_root, request.endpoint)
      : request.operation === 'lossless-inventory'
        ? await losslessInventory(request.tenant_root, request.relative_path, request.endpoint)
        : await losslessApply(
          request.tenant_root,
          request.relative_path,
          request.endpoint,
          request.plan,
        );
  process.stdout.write(`${JSON.stringify(response)}\n`);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : 'unknown runner failure';
  process.stderr.write(`metis-brain runner failed: ${message}\n`);
  process.exitCode = 1;
});
