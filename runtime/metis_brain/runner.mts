/**
 * Read-only Metis Brain runner.
 *
 * Python materializes an immutable session snapshot in a private temporary
 * directory and executes this file inside the pinned Metis archive sandbox.
 * The runner never writes a tenant, opens the network, or emits source text.
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

type Request = CompileRequest | CatalogRequest;

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
    if (bytes > 64 * 1024) { return fail('request exceeds the byte limit'); }
    chunks.push(chunk);
  }
  const value = exactObject(JSON.parse(Buffer.concat(chunks).toString('utf8')));
  if (value.schema_version !== 1 || !['compile', 'semantic-catalog'].includes(String(value.operation))) {
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
  if (Object.keys(value).sort().join(',') !== 'endpoint,operation,schema_version,tenant_root') {
    return fail('compile request has an invalid field roster');
  }
  const endpoint = value.endpoint;
  if (endpoint !== null && (typeof endpoint !== 'string' || endpoint.length === 0 || endpoint.length > 256)) {
    return fail('endpoint is invalid');
  }
  return { schema_version: 1, operation: 'compile', tenant_root: tenantRoot, endpoint };
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
    : await compile(request.tenant_root, request.endpoint);
  process.stdout.write(`${JSON.stringify(response)}\n`);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : 'unknown runner failure';
  process.stderr.write(`metis-brain runner failed: ${message}\n`);
  process.exitCode = 1;
});
