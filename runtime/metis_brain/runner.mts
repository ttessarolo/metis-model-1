/**
 * Read-only Metis Brain runner.
 *
 * Python materializes an immutable session snapshot in a private temporary
 * directory and executes this file inside the pinned Metis archive sandbox.
 * The runner never writes a tenant or opens the network. Source text is emitted
 * only inside the bounded lossless receipt returned to its Python caller.
 */
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import {
  AstUtils,
  CstUtils,
  GrammarUtils,
  stream,
  type AstNode,
  type LangiumDocuments,
} from "../../tooling/node_modules/langium/lib/index.js";
import {
  buildRuntimeCtx,
  compileTenantEndpoints,
  loadTenantDocs,
  tenantErrors,
} from "../../tooling/src/compiler/tenant-build.js";
import type {
  IrBlock,
  IrEndpoint,
  IrFetch,
  IrOrigin,
  IrPredicate,
} from "../../tooling/src/compiler/ir.js";
import { parseIr } from "../../tooling/src/compiler/serialize.js";
import { tenantIdFromMetisToml } from "../../tooling/src/compiler/tenant-artifact-set.js";
import {
  describeTenant,
  valuesForField,
  type FieldSkeleton,
  type TenantContext,
} from "../../tooling/src/cli/catalog-domain.js";
import { catalogThresholds } from "../../tooling/src/language/field-values.js";
import { driverOf } from "../../tooling/src/language/drivers-schema.js";
import { isCatalog, type Model } from "../../tooling/src/language/generated/ast.js";
import { OPENSEARCH_RECORD_SIMILARITY_BINDING } from "../../tooling/src/compiler/render-es.js";
import type {
  ArgRef,
  BlockArg,
  BlockInstance,
  Catalog,
  CountQty,
  Endpoint,
  FieldCondition,
  LimitStep,
  Literal,
  NamedBlock,
  ReturnFlow,
  Take,
  UseBlock,
  VariantDecl,
} from "../../tooling/src/language/generated/ast.js";

type CompileRequest = {
  schema_version: 1;
  operation: "compile";
  tenant_root: string;
  endpoint: string | null;
};

type CompileStructureRequest = {
  schema_version: 1;
  operation: "compile-structure";
  tenant_root: string;
  endpoint: string;
};

type CompileCandidateRequest = {
  schema_version: 1;
  operation: "compile-candidate";
  tenant_root: string;
  endpoint: string;
};

type CatalogRequest = {
  schema_version: 1;
  operation: "semantic-catalog";
  tenant_root: string;
};

type LosslessInventoryRequest = {
  schema_version: 1;
  operation: "lossless-inventory";
  tenant_root: string;
  relative_path: string;
  endpoint: string;
};

type LosslessApplyRequest = {
  schema_version: 1;
  operation: "lossless-apply";
  tenant_root: string;
  relative_path: string;
  endpoint: string;
  plan: unknown;
};

type EditSurfaceRequest = {
  schema_version: 1;
  operation: "edit-surface";
  tenant_root: string;
  relative_path: string;
  endpoint: string;
};

type Request =
  | CompileRequest
  | CompileCandidateRequest
  | CompileStructureRequest
  | CatalogRequest
  | EditSurfaceRequest
  | LosslessInventoryRequest
  | LosslessApplyRequest;

function fail(message: string): never {
  throw new Error(message);
}

function exactObject(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return fail("request must be an object");
  }
  return value as Record<string, unknown>;
}

async function readRequest(): Promise<Request> {
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const raw of process.stdin) {
    const chunk = Buffer.from(raw as Uint8Array);
    bytes += chunk.length;
    if (bytes > 256 * 1024) {
      return fail("request exceeds the byte limit");
    }
    chunks.push(chunk);
  }
  const value = exactObject(JSON.parse(Buffer.concat(chunks).toString("utf8")));
  if (
    value.schema_version !== 1 ||
    ![
      "compile",
      "compile-candidate",
      "compile-structure",
      "edit-surface",
      "semantic-catalog",
      "lossless-inventory",
      "lossless-apply",
    ].includes(String(value.operation))
  ) {
    return fail("request identity is invalid");
  }
  const tenantRoot = value.tenant_root;
  if (
    typeof tenantRoot !== "string" ||
    !path.isAbsolute(tenantRoot) ||
    tenantRoot.includes("\0")
  ) {
    return fail("tenant root is invalid");
  }
  if (value.operation === "semantic-catalog") {
    if (
      Object.keys(value).sort().join(",") !==
      "operation,schema_version,tenant_root"
    ) {
      return fail("catalog request has an invalid field roster");
    }
    return {
      schema_version: 1,
      operation: "semantic-catalog",
      tenant_root: tenantRoot,
    };
  }
  if (
    value.operation === "lossless-inventory" ||
    value.operation === "lossless-apply" ||
    value.operation === "edit-surface"
  ) {
    const expected =
      value.operation === "lossless-inventory" ||
      value.operation === "edit-surface"
        ? "endpoint,operation,relative_path,schema_version,tenant_root"
        : "endpoint,operation,plan,relative_path,schema_version,tenant_root";
    if (Object.keys(value).sort().join(",") !== expected) {
      return fail("lossless request has an invalid field roster");
    }
    const relativePath = value.relative_path;
    const endpoint = value.endpoint;
    if (
      typeof relativePath !== "string" ||
      !relativePath.endsWith(".metis") ||
      relativePath.includes("\\") ||
      relativePath.includes("\0") ||
      relativePath
        .split("/")
        .some(
          (part) => !part || part === "." || part === ".." || part === ".git",
        )
    ) {
      return fail("lossless relative path is invalid");
    }
    if (
      typeof endpoint !== "string" ||
      endpoint.length === 0 ||
      endpoint.length > 256
    ) {
      return fail("lossless endpoint is invalid");
    }
    if (value.operation === "lossless-inventory") {
      return {
        schema_version: 1,
        operation: "lossless-inventory",
        tenant_root: tenantRoot,
        relative_path: relativePath,
        endpoint,
      };
    }
    if (value.operation === "edit-surface") {
      return {
        schema_version: 1,
        operation: "edit-surface",
        tenant_root: tenantRoot,
        relative_path: relativePath,
        endpoint,
      };
    }
    return {
      schema_version: 1,
      operation: "lossless-apply",
      tenant_root: tenantRoot,
      relative_path: relativePath,
      endpoint,
      plan: value.plan,
    };
  }
  if (
    Object.keys(value).sort().join(",") !==
    "endpoint,operation,schema_version,tenant_root"
  ) {
    return fail("compile request has an invalid field roster");
  }
  const endpoint = value.endpoint;
  if (endpoint !== null && typeof endpoint !== "string") {
    return fail("endpoint is invalid");
  }
  if (
    typeof endpoint === "string" &&
    (endpoint.length === 0 || endpoint.length > 256)
  ) {
    return fail("endpoint is invalid");
  }
  if (
    value.operation === "compile-structure" ||
    value.operation === "compile-candidate"
  ) {
    if (typeof endpoint !== "string") {
      return fail("private compiler endpoint is invalid");
    }
    return {
      schema_version: 1,
      operation: value.operation,
      tenant_root: tenantRoot,
      endpoint,
    };
  }
  return {
    schema_version: 1,
    operation: "compile",
    tenant_root: tenantRoot,
    endpoint,
  };
}

function tenantSourcePath(tenantRoot: string, relativePath: string): string {
  const root = fs.realpathSync(tenantRoot);
  const candidate = path.resolve(root, ...relativePath.split("/"));
  const prefix = root.endsWith(path.sep) ? root : `${root}${path.sep}`;
  if (!candidate.startsWith(prefix)) {
    return fail("lossless target escapes the tenant");
  }
  const status = fs.lstatSync(candidate);
  if (!status.isFile() || status.isSymbolicLink()) {
    return fail("lossless target is not a regular file");
  }
  const resolved = fs.realpathSync(candidate);
  if (!resolved.startsWith(prefix)) {
    return fail("lossless target resolves outside the tenant");
  }
  return resolved;
}

function exactNode(
  inventory: {
    nodes: Array<{
      id: string;
      type: string;
      span: {
        offset: number;
        end: number;
        byteOffset: number;
        byteEnd: number;
      };
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
  if (typeof type !== "string" || cst === undefined) {
    return fail("lossless AST target has no CST identity");
  }
  const matches = inventory.nodes.filter(
    (item) =>
      item.type === type &&
      item.span.offset === cst.offset &&
      item.span.end === cst.end,
  );
  if (matches.length !== 1) {
    return fail("lossless AST target does not map uniquely to inventory");
  }
  return matches[0]!;
}

async function losslessInventory(
  tenantRoot: string,
  relativePath: string,
  requestedEndpoint: string,
): Promise<Record<string, unknown>> {
  const sourcePath = tenantSourcePath(tenantRoot, relativePath);
  const source = fs.readFileSync(sourcePath);
  const { buildInventory } =
    await import("../../tooling/src/lossless/inventory.js");
  const result = buildInventory(source);
  if (!result.ok) {
    return {
      schema_version: 1,
      operation: "lossless-inventory",
      status: "rejected",
      relative_path: relativePath,
      endpoint: requestedEndpoint,
      inventory: null,
      target: null,
      reasons: result.reasons,
    };
  }
  const docs = await loadTenantDocs(tenantRoot, { validate: true });
  const diagnostics = tenantErrors(docs);
  if (diagnostics.length > 0) {
    return fail(`tenant validation failed (${diagnostics.length} diagnostics)`);
  }
  const targetDocs = docs.filter(
    (doc) => fs.realpathSync(doc.uri.fsPath) === sourcePath,
  );
  if (targetDocs.length !== 1) {
    return fail("lossless target document is not unique");
  }
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
        clauses?: Array<{
          $type?: unknown;
          $cstNode?: { offset: number; end: number };
        }>;
      }>;
    }>;
  };
  const endpoints = (model.elements ?? []).filter(
    (item) => item.$type === "Endpoint" && item.name === requestedEndpoint,
  );
  if (endpoints.length !== 1) {
    return fail("lossless endpoint is not unique in target document");
  }
  const endpoint = endpoints[0]!;
  const takes = (endpoint.members ?? []).filter(
    (item) => item.$type === "Take",
  );
  if (takes.length !== 1) {
    return fail("lossless endpoint does not have one direct take");
  }
  const take = takes[0]!;
  const includes = (take.clauses ?? []).filter(
    (item) => item.$type === "IncludeClause",
  );
  if (includes.length !== 1) {
    return fail("lossless take does not have one direct include clause");
  }
  const include = includes[0]!;
  const endpointNode = exactNode(result.inventory, endpoint);
  const takeNode = exactNode(result.inventory, take);
  const includeNode = exactNode(result.inventory, include);
  const takeShape =
    take.page === true
      ? {
          mode: "page",
          value: typeof take.pageDefault === "number" ? take.pageDefault : null,
        }
      : {
          mode: "count",
          value: typeof take.count === "number" ? take.count : null,
        };
  if (
    takeShape.value !== null &&
    (!Number.isSafeInteger(takeShape.value) || takeShape.value <= 0)
  ) {
    return fail("lossless take shape is invalid");
  }
  return {
    schema_version: 1,
    operation: "lossless-inventory",
    status: "ok",
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

const EDIT_SURFACE_CONTRACT = "metis-brain-edit-surface/v1";
const MAX_EDIT_SURFACE_AST_NODES = 16_384;
const MAX_EDIT_SURFACE_ITEMS = 256;
const MAX_EDIT_SURFACE_ANCESTORS = 16;
const MAX_EDIT_SURFACE_ACTIVATION_TOKENS = 512;
const MAX_EDIT_SURFACE_SELECTORS = 128;
const MAX_EDIT_SURFACE_TEXT_UNITS = 512;
const MAX_EDIT_SURFACE_BYTES = 4 * 1024 * 1024;

type EditPrimitive =
  | "take_cardinality"
  | "output_limit"
  | "display_label_or_title"
  | "block_argument_list";

type ExplicitSpan = {
  utf16: { start: number; end: number };
  utf8_bytes: { start: number; end: number };
};

type EditSurfaceInventory = {
  sourceSha256: string;
  nodes: Array<{
    id: string;
    type: string;
    span: {
      offset: number;
      end: number;
      byteOffset: number;
      byteEnd: number;
    };
    preimageSha256: string;
  }>;
};

type EditSurfaceCandidate = {
  primitive: EditPrimitive;
  propertyOffset: number;
  occurrenceKey: string;
  item: Record<string, unknown>;
};

type BlockArgumentAuthority = {
  bindings: Array<{ catalog: string; field: string }>;
};

class EditSurfaceError extends Error {
  constructor(
    readonly code:
      | "BRAIN_EDIT_SURFACE_AMBIGUOUS"
      | "BRAIN_EDIT_SURFACE_INVALID"
      | "BRAIN_EDIT_SURFACE_LIMIT",
    message: string,
  ) {
    super(message);
  }
}

function explicitSpan(span: {
  offset: number;
  end: number;
  byteOffset: number;
  byteEnd: number;
}): ExplicitSpan {
  return {
    utf16: { start: span.offset, end: span.end },
    utf8_bytes: { start: span.byteOffset, end: span.byteEnd },
  };
}

function boundedEditText(value: string, label: string): string {
  if (value.length > MAX_EDIT_SURFACE_TEXT_UNITS) {
    throw new EditSurfaceError(
      "BRAIN_EDIT_SURFACE_LIMIT",
      `${label} exceeds the edit-surface text limit`,
    );
  }
  return value;
}

function exactEditInteger(
  value: number,
  label: string,
  minimum: number,
): number {
  if (!Number.isSafeInteger(value) || value < minimum) {
    throw new EditSurfaceError(
      "BRAIN_EDIT_SURFACE_INVALID",
      `${label} is not an exact supported integer`,
    );
  }
  return value;
}

function isQuotedStringValue(node: Literal): boolean {
  const properties = GrammarUtils.findNodesForProperty(node.$cstNode, "value");
  if (properties.length !== 1) {
    throw new EditSurfaceError(
      "BRAIN_EDIT_SURFACE_AMBIGUOUS",
      "block argument literal does not map uniquely to CST",
    );
  }
  const tokens = CstUtils.flattenCst(properties[0]!)
    .filter((token) => !token.hidden)
    .toArray();
  return tokens.length === 1 && tokens[0]!.tokenType.name === "STRING";
}

function containingCatalog(node: AstNode): Catalog | undefined {
  let current: AstNode | undefined = node;
  while (current !== undefined) {
    if (current.$type === "Catalog") return current as Catalog;
    current = current.$container;
  }
  return undefined;
}

function blockArgumentAuthority(argument: BlockArg): BlockArgumentAuthority {
  const template = argument.$container.template.ref;
  if (template === undefined) {
    throw new EditSurfaceError(
      "BRAIN_EDIT_SURFACE_INVALID",
      "block argument template is unresolved",
    );
  }
  const bindings = new Map<string, { catalog: string; field: string }>();
  for (const node of AstUtils.streamAst(template)) {
    if (node.$type !== "FieldCondition") continue;
    const condition = node as FieldCondition;
    if (
      condition.value?.$type !== "ArgRef" ||
      (condition.value as ArgRef).name !== argument.name
    ) {
      continue;
    }
    const field = condition.field.field.ref;
    const catalog = field === undefined ? undefined : containingCatalog(field);
    if (field === undefined || catalog === undefined) {
      throw new EditSurfaceError(
        "BRAIN_EDIT_SURFACE_INVALID",
        "block argument field authority is unresolved",
      );
    }
    const binding = {
      catalog: boundedEditText(catalog.name, "block argument catalog"),
      field: boundedEditText(field.name, "block argument field"),
    };
    bindings.set(`${binding.catalog}\0${binding.field}`, binding);
  }
  return {
    bindings: [...bindings.values()].sort(
      (left, right) =>
        left.catalog.localeCompare(right.catalog) ||
        left.field.localeCompare(right.field),
    ),
  };
}

function editNodeIdentity(
  inventory: EditSurfaceInventory,
  node: AstNode,
): {
  node_id: string;
  node_type: string;
  preimage_sha256: string;
  span: ExplicitSpan;
} {
  const match = exactNode(inventory, node);
  return {
    node_id: match.id,
    node_type: match.type,
    preimage_sha256: match.preimageSha256,
    span: explicitSpan(match.span),
  };
}

function exactPropertyAnchor(
  inventory: EditSurfaceInventory,
  owner: AstNode,
  propertyOwner: AstNode,
  propertyPath: string,
  propertyName: string,
  sourceText: string,
  byteAt: Uint32Array,
  valueNode?: AstNode,
): {
  ast_node_id: string | null;
  path: string;
  preimage_sha256: string;
  span: ExplicitSpan;
} {
  const matches = GrammarUtils.findNodesForProperty(
    propertyOwner.$cstNode,
    propertyName,
  );
  if (matches.length !== 1) {
    const ownerIdentity = editNodeIdentity(inventory, owner);
    throw new EditSurfaceError(
      "BRAIN_EDIT_SURFACE_AMBIGUOUS",
      `editable property ${propertyPath} of ${ownerIdentity.node_id} does not map uniquely to CST`,
    );
  }
  const token = matches[0]!;
  const span = {
    offset: token.offset,
    end: token.end,
    byteOffset: byteAt[token.offset]!,
    byteEnd: byteAt[token.end]!,
  };
  return {
    ast_node_id:
      valueNode === undefined
        ? null
        : editNodeIdentity(inventory, valueNode).node_id,
    path: propertyPath,
    preimage_sha256: sha256(sourceText.slice(token.offset, token.end)),
    span: explicitSpan(span),
  };
}

function editAncestorChain(owner: AstNode, endpoint: Endpoint): AstNode[] {
  const reversed: AstNode[] = [];
  let cursor: AstNode | undefined = owner;
  while (cursor !== undefined) {
    reversed.push(cursor);
    if (cursor === endpoint) {
      break;
    }
    cursor = cursor.$container;
    if (reversed.length > MAX_EDIT_SURFACE_ANCESTORS) {
      throw new EditSurfaceError(
        "BRAIN_EDIT_SURFACE_LIMIT",
        "editable node exceeds the edit-surface ancestor limit",
      );
    }
  }
  if (reversed.at(-1) !== endpoint) {
    throw new EditSurfaceError(
      "BRAIN_EDIT_SURFACE_INVALID",
      "editable node is not owned by the requested endpoint",
    );
  }
  return reversed.reverse();
}

function staticTitle(node: AstNode): string | null {
  if (
    ["NamedBlock", "VariantDecl", "BlockInstance"].includes(node.$type) &&
    typeof (node as { title?: unknown }).title === "string"
  ) {
    return boundedEditText((node as { title: string }).title, "scope label");
  }
  return null;
}

function scopeName(node: AstNode): string | null {
  if (node.$type === "Endpoint") {
    return boundedEditText((node as Endpoint).name, "endpoint name");
  }
  if (node.$type === "VariantDecl" || node.$type === "NamedBlock") {
    const name = (node as VariantDecl | NamedBlock).name;
    return typeof name === "string"
      ? boundedEditText(name, "scope name")
      : null;
  }
  if (node.$type === "BlockInstance") {
    const instance = node as BlockInstance;
    const name = instance.name ?? instance.template.$refText;
    return typeof name === "string"
      ? boundedEditText(name, "use-instance name")
      : null;
  }
  return null;
}

function scopeKind(
  node: AstNode,
): "endpoint" | "variant" | "block" | "use_instance" | null {
  if (node.$type === "Endpoint") return "endpoint";
  if (node.$type === "VariantDecl") return "variant";
  if (node.$type === "NamedBlock") return "block";
  if (node.$type === "BlockInstance") return "use_instance";
  return null;
}

function guardOf(node: AstNode): AstNode | undefined {
  if (
    node.$type === "VariantDecl" ||
    node.$type === "NamedBlock" ||
    node.$type === "Take"
  ) {
    return (node as VariantDecl | NamedBlock | Take).guard;
  }
  return undefined;
}

function decodedStringToken(text: string): string {
  if (text.startsWith('"')) {
    const parsed = JSON.parse(text) as unknown;
    if (typeof parsed === "string") {
      return parsed;
    }
  }
  if (text.startsWith("'") && text.endsWith("'")) {
    return text.slice(1, -1);
  }
  throw new EditSurfaceError(
    "BRAIN_EDIT_SURFACE_INVALID",
    "validated string selector cannot be decoded",
  );
}

function activationSurface(
  chain: AstNode[],
  stage: Take | ReturnFlow | UseBlock | BlockInstance,
  inventory: EditSurfaceInventory,
): {
  activation_sha256: string | null;
  selectors: { identifiers: string[]; string_literals: string[] };
} {
  const signatures: Array<Record<string, unknown>> = [];
  const stageIdentifiers: string[] = [];
  const stageStringLiterals: string[] = [];
  let tokenCount = 0;
  const appendSelector = (
    items: string[],
    value: string,
    label: string,
  ): void => {
    const bounded = boundedEditText(value, label);
    if (!items.includes(bounded)) {
      items.push(bounded);
      if (items.length > MAX_EDIT_SURFACE_SELECTORS) {
        throw new EditSurfaceError(
          "BRAIN_EDIT_SURFACE_LIMIT",
          "activation selectors exceed the edit-surface limit",
        );
      }
    }
  };
  for (const node of chain) {
    const guard = guardOf(node);
    if (guard?.$cstNode === undefined) continue;
    const tokens = CstUtils.flattenCst(guard.$cstNode)
      .filter((token) => !token.hidden)
      .map((token) => {
        tokenCount += 1;
        if (tokenCount > MAX_EDIT_SURFACE_ACTIVATION_TOKENS) {
          throw new EditSurfaceError(
            "BRAIN_EDIT_SURFACE_LIMIT",
            "activation tokens exceed the edit-surface limit",
          );
        }
        if (node === stage && token.tokenType.name === "ID") {
          appendSelector(stageIdentifiers, token.text, "activation identifier");
        } else if (node === stage && token.tokenType.name === "STRING") {
          appendSelector(
            stageStringLiterals,
            decodedStringToken(token.text),
            "activation string literal",
          );
        }
        return { token: token.tokenType.name, text: token.text };
      })
      .toArray();
    signatures.push({
      owner_node_id: editNodeIdentity(inventory, node).node_id,
      tokens,
    });
  }
  return {
    activation_sha256:
      signatures.length === 0 ? null : canonicalHash(signatures),
    // The digest protects the whole ancestor-to-stage activation chain. The
    // selectors are deliberately stage-local: flattening an ancestor variant's
    // HDR|SDR guard into both child takes would make the siblings identical.
    selectors: {
      identifiers: stageIdentifiers,
      string_literals: stageStringLiterals,
    },
  };
}

function stageKind(
  node: Take | ReturnFlow | UseBlock | BlockInstance,
): "take" | "return_flow" | "use_block" | "use_instance" {
  if (node.$type === "Take") return "take";
  if (node.$type === "ReturnFlow") return "return_flow";
  if (node.$type === "UseBlock") return "use_block";
  return "use_instance";
}

function stageIdentifier(
  node: Take | ReturnFlow | UseBlock | BlockInstance,
): string | null {
  if (node.$type === "Take") {
    return typeof node.name === "string"
      ? boundedEditText(node.name, "take name")
      : null;
  }
  if (node.$type === "UseBlock") {
    return boundedEditText(node.block.$refText, "use-block reference");
  }
  if (node.$type === "BlockInstance") {
    return boundedEditText(
      node.name ?? node.template.$refText,
      "use-instance identifier",
    );
  }
  return null;
}

function editScope(
  endpoint: Endpoint,
  owner: AstNode,
  stage: Take | ReturnFlow | UseBlock | BlockInstance,
  inventory: EditSurfaceInventory,
): {
  ancestors: Array<{
    kind: "endpoint" | "variant" | "block" | "use_instance";
    node_id: string;
    name: string | null;
    label: string | null;
  }>;
  stage: {
    kind: "take" | "return_flow" | "use_block" | "use_instance";
    node_id: string;
    identifier: string | null;
    activation_sha256: string | null;
    selectors: { identifiers: string[]; string_literals: string[] };
  };
  occurrence: number;
} {
  const chain = editAncestorChain(owner, endpoint);
  const ancestors = chain.flatMap((node) => {
    const kind = scopeKind(node);
    if (kind === null) return [];
    return [
      {
        kind,
        node_id: editNodeIdentity(inventory, node).node_id,
        name: scopeName(node),
        label: staticTitle(node),
      },
    ];
  });
  const activation = activationSurface(chain, stage, inventory);
  return {
    ancestors,
    stage: {
      kind: stageKind(stage),
      node_id: editNodeIdentity(inventory, stage).node_id,
      identifier: stageIdentifier(stage),
      ...activation,
    },
    occurrence: 0,
  };
}

function invalidEditSurface(
  relativePath: string,
  requestedEndpoint: string,
  code: string,
  message: string,
  diagnostics: unknown[] = [],
): Record<string, unknown> {
  return {
    schema_version: 1,
    operation: "edit-surface",
    status: "invalid",
    diagnostics:
      diagnostics.length > 0
        ? diagnostics
        : [{ file: "", line: 1, code, message }],
    relative_path: relativePath,
    endpoint: requestedEndpoint,
    edit_surface: null,
    edit_surface_sha256: null,
  };
}

async function editSurface(
  tenantRoot: string,
  relativePath: string,
  requestedEndpoint: string,
): Promise<Record<string, unknown>> {
  const sourcePath = tenantSourcePath(tenantRoot, relativePath);
  const source = fs.readFileSync(sourcePath);
  const sourceText = source.toString("utf8");
  const { buildInventory, byteOffsetMap } =
    await import("../../tooling/src/lossless/inventory.js");
  const inventoryResult = buildInventory(source);
  if (!inventoryResult.ok) {
    return invalidEditSurface(
      relativePath,
      requestedEndpoint,
      "BRAIN_EDIT_SURFACE_SOURCE",
      "edit-surface source is not lossless-admissible",
      inventoryResult.reasons,
    );
  }
  const inventory = inventoryResult.inventory as EditSurfaceInventory;
  const docs = await loadTenantDocs(tenantRoot, { validate: true });
  const targetDocs = docs.filter(
    (doc) => fs.realpathSync(doc.uri.fsPath) === sourcePath,
  );
  if (targetDocs.length !== 1) {
    return invalidEditSurface(
      relativePath,
      requestedEndpoint,
      "BRAIN_EDIT_SURFACE_AMBIGUOUS",
      "edit-surface target document is not unique",
    );
  }
  const model = targetDocs[0]!.parseResult.value as {
    elements?: AstNode[];
  };
  const endpointMatches = (model.elements ?? []).filter(
    (node) =>
      node.$type === "Endpoint" &&
      (node as Endpoint).name === requestedEndpoint,
  ) as Endpoint[];
  if (endpointMatches.length !== 1) {
    return invalidEditSurface(
      relativePath,
      requestedEndpoint,
      "BRAIN_ENDPOINT_IDENTITY",
      endpointMatches.length === 0
        ? "edit-surface endpoint is not present in the target document"
        : "edit-surface endpoint is ambiguous in the target document",
    );
  }
  const diagnostics = tenantErrors(docs).slice(0, 128);
  if (diagnostics.length > 0) {
    return invalidEditSurface(
      relativePath,
      requestedEndpoint,
      "BRAIN_TENANT_INVALID",
      "edit-surface tenant snapshot is invalid",
      diagnostics,
    );
  }
  const compiled = compileTenantEndpoints(docs, tenantRoot);
  if (!compiled.has(requestedEndpoint)) {
    return invalidEditSurface(
      relativePath,
      requestedEndpoint,
      "BRAIN_ENDPOINT_IDENTITY",
      "edit-surface endpoint is not compiler-owned",
    );
  }

  const endpoint = endpointMatches[0]!;
  const endpointIdentity = editNodeIdentity(inventory, endpoint);
  const byteAt = byteOffsetMap(sourceText);
  const candidates: EditSurfaceCandidate[] = [];
  let astNodes = 0;
  const append = (
    primitive: EditPrimitive,
    owner: AstNode,
    stage: Take | ReturnFlow | UseBlock | BlockInstance,
    property: ReturnType<typeof exactPropertyAnchor>,
    oldValue: Record<string, unknown>,
  ): void => {
    if (candidates.length >= MAX_EDIT_SURFACE_ITEMS) {
      throw new EditSurfaceError(
        "BRAIN_EDIT_SURFACE_LIMIT",
        "endpoint has too many editable surface items",
      );
    }
    const ownerIdentity = editNodeIdentity(inventory, owner);
    const scope = editScope(endpoint, owner, stage, inventory);
    const structuralOwner = scope.ancestors.at(-1);
    if (structuralOwner === undefined) {
      throw new EditSurfaceError(
        "BRAIN_EDIT_SURFACE_INVALID",
        "editable node has no structural owner",
      );
    }
    candidates.push({
      primitive,
      propertyOffset: property.span.utf16.start,
      occurrenceKey: `${structuralOwner.node_id}\0${scope.stage.kind}\0${primitive}`,
      item: {
        ordinal: 0,
        edit_ref: "",
        primitive,
        owner: ownerIdentity,
        property,
        scope,
        old_value: oldValue,
        authority:
          primitive === "block_argument_list"
            ? blockArgumentAuthority(owner as BlockArg)
            : null,
      },
    });
  };

  try {
    for (const node of AstUtils.streamAst(endpoint)) {
      astNodes += 1;
      if (astNodes > MAX_EDIT_SURFACE_AST_NODES) {
        throw new EditSurfaceError(
          "BRAIN_EDIT_SURFACE_LIMIT",
          "endpoint AST exceeds the edit-surface node limit",
        );
      }
      if (node.$type === "Take") {
        const take = node as Take;
        if (typeof take.count === "number") {
          append(
            "take_cardinality",
            take,
            take,
            exactPropertyAnchor(
              inventory,
              take,
              take,
              "count",
              "count",
              sourceText,
              byteAt,
            ),
            {
              type: "positive_integer",
              mode: "count",
              value: exactEditInteger(take.count, "take count", 1),
            },
          );
        } else if (take.page && typeof take.pageDefault === "number") {
          append(
            "take_cardinality",
            take,
            take,
            exactPropertyAnchor(
              inventory,
              take,
              take,
              "pageDefault",
              "pageDefault",
              sourceText,
              byteAt,
            ),
            {
              type: "positive_integer",
              mode: "page_default",
              value: exactEditInteger(take.pageDefault, "take page default", 1),
            },
          );
        }
        if (typeof take.title === "string") {
          append(
            "display_label_or_title",
            take,
            take,
            exactPropertyAnchor(
              inventory,
              take,
              take,
              "title",
              "title",
              sourceText,
              byteAt,
            ),
            {
              type: "string",
              value: boundedEditText(take.title, "take display label"),
            },
          );
        }
      } else if (node.$type === "LimitStep") {
        const limit = node as LimitStep;
        const quantity = limit.quantity;
        if (
          quantity.$type === "CountQty" &&
          (quantity as CountQty).n.$type === "CardinalityLiteral"
        ) {
          const count = quantity as CountQty;
          const literal = count.n;
          const stage = limit.$container;
          if (stage.$type !== "ReturnFlow") {
            continue;
          }
          append(
            "output_limit",
            limit,
            stage,
            exactPropertyAnchor(
              inventory,
              limit,
              count,
              "quantity.n.value",
              "n",
              sourceText,
              byteAt,
              literal,
            ),
            {
              type: "non_negative_integer",
              unit: count.percent ? "percent" : "items",
              value: exactEditInteger(literal.value, "output limit", 0),
            },
          );
        }
      } else if (node.$type === "UseBlock") {
        const use = node as UseBlock;
        if (typeof use.title === "string") {
          append(
            "display_label_or_title",
            use,
            use,
            exactPropertyAnchor(
              inventory,
              use,
              use,
              "title",
              "title",
              sourceText,
              byteAt,
            ),
            {
              type: "string",
              value: boundedEditText(use.title, "use-block display label"),
            },
          );
        }
      } else if (node.$type === "BlockInstance") {
        const instance = node as BlockInstance;
        if (typeof instance.title === "string") {
          append(
            "display_label_or_title",
            instance,
            instance,
            exactPropertyAnchor(
              inventory,
              instance,
              instance,
              "title",
              "title",
              sourceText,
              byteAt,
            ),
            {
              type: "string",
              value: boundedEditText(
                instance.title,
                "use-instance display label",
              ),
            },
          );
        }
      } else if (node.$type === "BlockArg") {
        const argument = node as BlockArg;
        if (
          argument.value.$type === "Literal" &&
          typeof (argument.value as Literal).value === "string" &&
          isQuotedStringValue(argument.value as Literal)
        ) {
          const literal = argument.value as Literal;
          append(
            "block_argument_list",
            argument,
            argument.$container,
            exactPropertyAnchor(
              inventory,
              argument,
              argument,
              "value.value",
              "value",
              sourceText,
              byteAt,
              literal,
            ),
            {
              type: "string",
              argument: boundedEditText(argument.name, "block argument name"),
              value: boundedEditText(
                literal.value as string,
                "block argument string literal",
              ),
            },
          );
        }
      }
    }

    candidates.sort(
      (left, right) =>
        left.propertyOffset - right.propertyOffset ||
        left.primitive.localeCompare(right.primitive) ||
        String((left.item.owner as { node_id: string }).node_id).localeCompare(
          String((right.item.owner as { node_id: string }).node_id),
        ),
    );
    const occurrences = new Map<string, number>();
    const items = candidates.map((candidate, ordinal) => {
      const occurrence = occurrences.get(candidate.occurrenceKey) ?? 0;
      occurrences.set(candidate.occurrenceKey, occurrence + 1);
      const scope = candidate.item.scope as { occurrence: number };
      scope.occurrence = occurrence;
      candidate.item.ordinal = ordinal;
      candidate.item.edit_ref = canonicalHash({
        contract: EDIT_SURFACE_CONTRACT,
        source_sha256: inventory.sourceSha256,
        primitive: candidate.primitive,
        owner_node_id: (candidate.item.owner as { node_id: string }).node_id,
        property: candidate.item.property,
        scope,
        authority: candidate.item.authority,
      });
      return candidate.item;
    });
    const editSurfaceProjection = {
      contract: EDIT_SURFACE_CONTRACT,
      relative_path: relativePath,
      source_sha256: inventory.sourceSha256,
      endpoint: {
        name: requestedEndpoint,
        node_id: endpointIdentity.node_id,
        preimage_sha256: endpointIdentity.preimage_sha256,
        span: endpointIdentity.span,
      },
      items,
      counts: {
        items: items.length,
        take_cardinality: candidates.filter(
          (item) => item.primitive === "take_cardinality",
        ).length,
        output_limit: candidates.filter(
          (item) => item.primitive === "output_limit",
        ).length,
        display_label_or_title: candidates.filter(
          (item) => item.primitive === "display_label_or_title",
        ).length,
        block_argument_list: candidates.filter(
          (item) => item.primitive === "block_argument_list",
        ).length,
      },
    };
    if (
      Buffer.byteLength(canonicalJson(editSurfaceProjection), "utf8") >
      MAX_EDIT_SURFACE_BYTES
    ) {
      throw new EditSurfaceError(
        "BRAIN_EDIT_SURFACE_LIMIT",
        "edit-surface projection exceeds its byte limit",
      );
    }
    return {
      schema_version: 1,
      operation: "edit-surface",
      status: "ok",
      diagnostics: [],
      relative_path: relativePath,
      endpoint: requestedEndpoint,
      edit_surface: editSurfaceProjection,
      edit_surface_sha256: canonicalHash(editSurfaceProjection),
    };
  } catch (error: unknown) {
    if (error instanceof EditSurfaceError) {
      return invalidEditSurface(
        relativePath,
        requestedEndpoint,
        error.code,
        error.message,
      );
    }
    return invalidEditSurface(
      relativePath,
      requestedEndpoint,
      "BRAIN_EDIT_SURFACE_INVALID",
      "endpoint edit surface cannot be projected safely",
    );
  }
}

async function losslessApply(
  tenantRoot: string,
  relativePath: string,
  requestedEndpoint: string,
  plan: unknown,
): Promise<Record<string, unknown>> {
  const sourcePath = tenantSourcePath(tenantRoot, relativePath);
  const source = fs.readFileSync(sourcePath);
  const { applyEditPlan } = await import("../../tooling/src/lossless/apply.js");
  const receipt = await applyEditPlan(source, plan, {
    compileProof: "validate",
    tenantDir: tenantRoot,
    sourcePath,
  });
  return {
    schema_version: 1,
    operation: "lossless-apply",
    status: receipt.outcome === "APPLIED" ? "ok" : "rejected",
    relative_path: relativePath,
    endpoint: requestedEndpoint,
    proof_mode: "validate",
    receipt,
  };
}

async function context(tenantRoot: string): Promise<TenantContext> {
  const metisToml = fs.readFileSync(
    path.join(tenantRoot, "metis.toml"),
    "utf8",
  );
  const tenant = tenantIdFromMetisToml(metisToml);
  const docs = await loadTenantDocs(tenantRoot, { validate: true });
  const diagnostics = tenantErrors(docs);
  if (diagnostics.length > 0) {
    return fail(`tenant validation failed (${diagnostics.length} diagnostics)`);
  }
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
    const fieldPath =
      parent === undefined ? field.name : `${parent}.${field.name}`;
    if (
      ["inline", "list", "enum"].includes(field.domain.kind) &&
      (field.domain.size ?? 0) > 0
    ) {
      result.push(fieldPath);
    }
    if (field.fields) {
      result.push(...finiteFields(field.fields, fieldPath));
    }
  }
  return result;
}

function technicalFields(
  fields: FieldSkeleton[],
  parent?: string,
): Array<{ name: string; type: string; modifiers: string[] }> {
  return fields.flatMap((field) => {
    const name = parent === undefined ? field.name : `${parent}.${field.name}`;
    return [
      { name, type: field.type, modifiers: [...field.modifiers] },
      ...technicalFields(field.fields ?? [], name),
    ];
  });
}

function catalogTechnicalAuthority(
  ctx: TenantContext,
  described: ReturnType<typeof describeTenant>,
): Record<string, unknown> {
  const catalogs = ctx.docs.flatMap((doc) =>
    (doc.parseResult.value as Model).elements.filter(isCatalog),
  );
  if (catalogs.length !== described.catalogs.length) {
    return fail("technical and semantic catalog counts differ");
  }
  return {
    contract_id: "metis-brain-tenant-technical-authority/v1",
    tenant: ctx.tenant,
    catalogs: catalogs.map((catalog, index) => {
      const skeleton = described.catalogs[index]!;
      const driver = driverOf(catalog.driver);
      if (skeleton.name !== catalog.name || driver === undefined) {
        return fail("technical catalog identity or driver is invalid");
      }
      return {
        name: catalog.name,
        driver: driver.name,
        capabilities: [...driver.features],
        fields: technicalFields(skeleton.fields),
        id_field: catalog.idField ?? null,
        similarity_field: catalog.similarity ?? null,
        similarity_profiles: catalog.profiles.map((profile) => ({
          name: profile.name,
          fields: profile.fields.map((field) => {
            const bound = field.field.ref;
            if (bound === undefined) {
              return fail("technical similarity field is unresolved");
            }
            return [bound.name, ...field.subfield].join(".");
          }),
          binding: OPENSEARCH_RECORD_SIMILARITY_BINDING,
        })),
        projections: catalog.returns.map((projection) => ({
          name: projection.name,
          fields: [...projection.fields],
        })),
      };
    }),
  };
}

async function semanticCatalog(
  tenantRoot: string,
): Promise<Record<string, unknown>> {
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
    operation: "semantic-catalog",
    describe,
    values,
    technical_authority: catalogTechnicalAuthority(ctx, describe),
    counts: {
      catalogs: describe.catalogs.length,
      finite_fields: values.length,
      values: values.reduce(
        (total, item) => total + (item.values?.length ?? 0),
        0,
      ),
    },
  };
}

function sha256(text: string): string {
  return `sha256:${createHash("sha256").update(text, "utf8").digest("hex")}`;
}

async function compile(
  tenantRoot: string,
  requestedEndpoint: string | null,
): Promise<Record<string, unknown>> {
  const docs = await loadTenantDocs(tenantRoot, { validate: true });
  const diagnostics = tenantErrors(docs).slice(0, 128);
  if (diagnostics.length > 0) {
    return {
      schema_version: 1,
      operation: "compile",
      status: "invalid",
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
    const matches = names.filter(
      (name) =>
        name === requestedEndpoint || name.endsWith(`.${requestedEndpoint}`),
    );
    if (matches.length !== 1) {
      return {
        schema_version: 1,
        operation: "compile",
        status: "invalid",
        diagnostics: [
          {
            file: "",
            line: 1,
            code: "BRAIN_ENDPOINT_IDENTITY",
            message:
              matches.length === 0
                ? "endpoint richiesto non compilato"
                : "endpoint richiesto ambiguo",
          },
        ],
        endpoint: null,
        endpoint_sha256: null,
        runtime_context_sha256: null,
      };
    }
    selected = matches[0];
  }
  const endpointSource =
    selected === null ? null : (compiled.get(selected) ?? null);
  const runtimeContext = JSON.stringify(buildRuntimeCtx(docs, tenantRoot));
  return {
    schema_version: 1,
    operation: "compile",
    status: "ok",
    diagnostics: [],
    endpoint: selected,
    endpoint_sha256: endpointSource === null ? null : sha256(endpointSource),
    runtime_context_sha256: sha256(runtimeContext),
  };
}

type ProvenanceTraversal = "node" | "node-array" | "node-map" | "data";

function stripProvenance(
  value: unknown,
  mode: ProvenanceTraversal = "node",
): unknown {
  if (Array.isArray(value)) {
    const childMode = mode === "node-array" ? "node" : "data";
    return value.map((member) => stripProvenance(member, childMode));
  }
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (mode === "node-map") {
      return Object.fromEntries(
        Object.entries(record).map(([key, member]) => [
          key,
          stripProvenance(member, "node"),
        ]),
      );
    }
    const node = mode === "node" ? record.node : null;
    const childMode = (key: string): ProvenanceTraversal => {
      if (node === "Endpoint") {
        if (key === "context") return "node-map";
        if (["blocks", "variants"].includes(key)) return "node-array";
        if (key === "inline") return "node";
      }
      if (node === "Block" && ["takes", "blocks"].includes(key)) {
        return "node-array";
      }
      return "data";
    };
    return Object.fromEntries(
      Object.entries(record)
        .filter(([key]) => !(mode === "node" && key === "provenance"))
        .map(([key, member]) => [key, stripProvenance(member, childMode(key))]),
    );
  }
  return value;
}

function canonicalJson(value: unknown): string {
  function normalize(member: unknown): unknown {
    if (Array.isArray(member)) {
      return member.map(normalize);
    }
    if (member !== null && typeof member === "object") {
      return Object.fromEntries(
        Object.entries(member as Record<string, unknown>)
          .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
          .map(([key, nested]) => [key, normalize(nested)]),
      );
    }
    return member;
  }
  return JSON.stringify(normalize(value));
}

const MAX_MANIFEST_CONTAINERS = 512;
const MAX_MANIFEST_FETCHES = 512;
const MAX_MANIFEST_PREDICATES = 8192;
const MAX_MANIFEST_CONTEXT_NODES = 512;
const MAX_MANIFEST_BYTES = 4 * 1024 * 1024;
const MAX_CANDIDATE_IR_BYTES = 4 * 1024 * 1024;
const MAX_CANDIDATE_IR_DEPTH = 128;
const MAX_CANDIDATE_IR_NODES = 100_000;

class CandidateManifestError extends Error {
  constructor(
    readonly code: "BRAIN_MANIFEST_LIMIT" | "BRAIN_CATALOG_LINEAGE",
    message: string,
  ) {
    super(message);
  }
}

function canonicalHash(value: unknown): string {
  return sha256(canonicalJson(value));
}

function hashWhenPresent(value: unknown): string | null {
  return value === undefined ? null : canonicalHash(value);
}

function fetchSemanticsHash(fetch: IrFetch): string {
  const normalized = stripProvenance(fetch) as Record<string, unknown>;
  delete normalized.stageId;
  return canonicalHash(normalized);
}

function containerSemanticsHash(
  container: IrEndpoint | IrBlock,
  kind: "endpoint" | "block",
): string {
  const normalized = stripProvenance(container) as Record<string, unknown>;
  if (kind === "block") {
    // Child structure has its own ordered container/fetch roster.  Everything
    // else is direct block semantics and must remain covered as the IR grows.
    delete normalized.takes;
    delete normalized.blocks;
    return canonicalHash(normalized);
  }

  delete normalized.blocks;
  delete normalized.variants;
  delete normalized.inline;
  const context = normalized.context;
  if (context !== undefined) {
    if (
      context === null ||
      typeof context !== "object" ||
      Array.isArray(context)
    ) {
      throw new CandidateManifestError(
        "BRAIN_MANIFEST_LIMIT",
        "candidate endpoint context is invalid",
      );
    }
    const entries = Object.entries(context as Record<string, unknown>);
    if (entries.length > MAX_MANIFEST_CONTEXT_NODES) {
      throw new CandidateManifestError(
        "BRAIN_MANIFEST_LIMIT",
        "candidate has too many context nodes",
      );
    }
    normalized.context = Object.fromEntries(
      entries.map(([name, node]) => {
        if (
          node !== null &&
          typeof node === "object" &&
          !Array.isArray(node) &&
          (node as Record<string, unknown>).node === "Fetch"
        ) {
          // The complete Fetch is separately manifested.  Retain the mapping
          // from context name to its compiler-owned occurrence identity here.
          return [
            name,
            {
              node: "Fetch",
              stageId: (node as Record<string, unknown>).stageId,
            },
          ];
        }
        // ContextTransform has no fetch occurrence, so its full direct IR
        // semantics (minus provenance) belongs to the endpoint container.
        return [name, node];
      }),
    );
  }
  return canonicalHash(normalized);
}

function fallbackHash(value: {
  fallback?: unknown;
  fallbacks?: unknown;
  materializedFallbacks?: unknown;
}): string | null {
  if (
    value.fallback === undefined &&
    value.fallbacks === undefined &&
    value.materializedFallbacks === undefined
  ) {
    return null;
  }
  return canonicalHash({
    fallback: value.fallback,
    fallbacks: value.fallbacks,
    materializedFallbacks: value.materializedFallbacks,
  });
}

function normalizedOrigin(origin: IrOrigin): {
  kind: string;
  ref: string | null;
} {
  return { kind: origin.kind, ref: origin.ref ?? null };
}

type ManifestPredicate = {
  intent: "include" | "exclude" | "promote";
  clause_index: number;
  leaf_path: string;
  catalog: string | null;
  field: string | null;
  operator: string;
  value: unknown;
  amount: unknown;
  graded: boolean;
  origin: { kind: string; ref: string | null };
  clause_guard_sha256: string | null;
  leaf_guard_sha256: string | null;
  expression_sha256: string;
};

function predicateLeaves(
  predicate: IrPredicate,
  path: string,
): Array<{ predicate: IrPredicate; path: string }> {
  if (
    !("args" in predicate) ||
    predicate.args === undefined ||
    !["group", "and", "or"].includes(predicate.op)
  ) {
    return [{ predicate, path }];
  }
  return predicate.args.flatMap((item, index) =>
    predicateLeaves(item, `${path}.args[${index}]`),
  );
}

function fetchPredicates(
  fetch: IrFetch,
  catalog: string | null,
): ManifestPredicate[] {
  const result: ManifestPredicate[] = [];
  const append = (
    intent: ManifestPredicate["intent"],
    clauseIndex: number,
    predicate: IrPredicate,
    origin: IrOrigin,
    clauseGuard: string | undefined,
    path: string,
  ): void => {
    const expressionSha256 = canonicalHash(predicate);
    for (const leaf of predicateLeaves(predicate, path)) {
      const item = leaf.predicate;
      result.push({
        intent,
        clause_index: clauseIndex,
        leaf_path: leaf.path,
        catalog,
        field: "field" in item ? (item.field ?? null) : null,
        operator: item.op,
        value: "value" in item ? (item.value ?? null) : null,
        amount: "amount" in item ? (item.amount ?? null) : null,
        graded: item.graded,
        origin: normalizedOrigin(origin),
        clause_guard_sha256: hashWhenPresent(clauseGuard),
        leaf_guard_sha256: "guard" in item ? hashWhenPresent(item.guard) : null,
        expression_sha256: expressionSha256,
      });
    }
  };
  fetch.constraints.forEach((clause, index) =>
    append(
      "include",
      index,
      clause.predicate,
      clause.origin,
      clause.guard,
      `constraints[${index}].predicate`,
    ),
  );
  fetch.exclusions.forEach((clause, index) =>
    clause.predicates.forEach((predicate, predicateIndex) =>
      append(
        "exclude",
        index,
        predicate,
        clause.origin,
        clause.guard,
        `exclusions[${index}].predicates[${predicateIndex}]`,
      ),
    ),
  );
  fetch.preferences.forEach((clause, index) =>
    append(
      "promote",
      index,
      clause.predicate,
      clause.origin,
      clause.guard,
      `preferences[${index}].predicate`,
    ),
  );
  return result;
}

function candidateManifest(
  endpoint: IrEndpoint,
  endpointSource: string,
): unknown {
  const containers: Array<Record<string, unknown>> = [];
  const fetches: Array<Record<string, unknown>> = [];
  let predicateCount = 0;

  const addContainer = (
    container: IrEndpoint | IrBlock,
    containerPath: string,
    kind: "endpoint" | "block",
  ): void => {
    if (containers.length >= MAX_MANIFEST_CONTAINERS) {
      throw new CandidateManifestError(
        "BRAIN_MANIFEST_LIMIT",
        "candidate has too many structural containers",
      );
    }
    const endpointNode = kind === "endpoint" ? (container as IrEndpoint) : null;
    const blockNode = kind === "block" ? (container as IrBlock) : null;
    containers.push({
      path: containerPath,
      kind,
      name: container.name,
      activation_sha256: hashWhenPresent(blockNode?.activation),
      output_sha256: hashWhenPresent(container.output),
      fallback_sha256: fallbackHash(container),
      uses_sha256: hashWhenPresent(blockNode?.uses),
      semantics_sha256: containerSemanticsHash(container, kind),
      presentation_sha256: canonicalHash(
        endpointNode === null
          ? {
              title: blockNode?.title,
              titleInterpolates: blockNode?.titleInterpolates,
              titleFallback: blockNode?.titleFallback,
              titleContextDeps: blockNode?.titleContextDeps,
              titleField: blockNode?.titleField,
              pinned: blockNode?.pinned,
              viewAll: blockNode?.viewAll,
              meta: blockNode?.meta,
              empty: blockNode?.empty,
            }
          : {
              reference: endpointNode.reference,
              expires: endpointNode.expires,
              paginate: endpointNode.paginate,
              analytics: endpointNode.analytics,
              cardinalityParams: endpointNode.cardinalityParams,
            },
      ),
    });
  };

  const addFetch = (fetch: IrFetch, containerPath: string): void => {
    if (fetches.length >= MAX_MANIFEST_FETCHES) {
      throw new CandidateManifestError(
        "BRAIN_MANIFEST_LIMIT",
        "candidate has too many fetch occurrences",
      );
    }
    const source = fetch.source;
    if (
      typeof source.ref !== "string" ||
      source.ref.length === 0 ||
      source.ref.length > 256
    ) {
      throw new CandidateManifestError(
        "BRAIN_CATALOG_LINEAGE",
        "candidate fetch source identity is unavailable",
      );
    }
    const provisionalCatalog = source.kind === "catalog" ? source.ref : null;
    const predicates = fetchPredicates(fetch, provisionalCatalog);
    // A field predicate over a context/list fetch is compiler-owned but has no
    // catalog lineage by construction (for example @ts on a user's watched
    // history).  Preserve it with catalog=null under the exact non-catalog
    // source occurrence; downstream create grounding still rejects it unless
    // separate authority exists, while manifest preservation can compare it.
    predicateCount += predicates.length;
    if (predicateCount > MAX_MANIFEST_PREDICATES) {
      throw new CandidateManifestError(
        "BRAIN_MANIFEST_LIMIT",
        "candidate has too many predicate leaves",
      );
    }
    fetches.push({
      occurrence: fetches.length,
      stage_id: fetch.stageId,
      container_path: containerPath,
      source: { kind: source.kind, ref: source.ref },
      catalog: provisionalCatalog,
      count: fetch.count,
      activation_sha256: hashWhenPresent(fetch.activation),
      ordering_sha256: canonicalHash(fetch.ordering),
      output_sha256: hashWhenPresent(fetch.output),
      fallback_sha256: fallbackHash(fetch),
      predicates,
      semantics_sha256: fetchSemanticsHash(fetch),
    });
  };

  const addBlock = (block: IrBlock, containerPath: string): void => {
    addContainer(block, containerPath, "block");
    block.takes.forEach((fetch) => addFetch(fetch, containerPath));
    (block.blocks ?? []).forEach((nested, index) =>
      addBlock(nested, `${containerPath}/blocks[${index}]:${nested.name}`),
    );
  };

  addContainer(endpoint, "endpoint", "endpoint");
  for (const [name, contextNode] of Object.entries(endpoint.context ?? {})) {
    if (contextNode.node === "Fetch") {
      addFetch(contextNode, `endpoint/context:${name}`);
    }
  }
  endpoint.blocks.forEach((block, index) =>
    addBlock(block, `endpoint/blocks[${index}]:${block.name}`),
  );
  endpoint.variants.forEach((variant, index) =>
    addBlock(variant, `endpoint/variants[${index}]:${variant.name}`),
  );
  if (endpoint.inline !== undefined) {
    addBlock(endpoint.inline, "endpoint/inline");
  }
  const endpointSha256 = sha256(endpointSource);
  const manifest = {
    schema_version: 1,
    endpoint: endpoint.name,
    endpoint_sha256: endpointSha256,
    containers,
    fetches,
  };
  if (Buffer.byteLength(canonicalJson(manifest), "utf8") > MAX_MANIFEST_BYTES) {
    throw new CandidateManifestError(
      "BRAIN_MANIFEST_LIMIT",
      "candidate structural manifest exceeds its byte limit",
    );
  }
  return manifest;
}

function candidateIr(endpoint: IrEndpoint, requestedEndpoint: string): unknown {
  const normalized = stripProvenance(endpoint);
  if (
    normalized === null ||
    typeof normalized !== "object" ||
    Array.isArray(normalized)
  ) {
    throw new CandidateManifestError(
      "BRAIN_MANIFEST_LIMIT",
      "candidate normalized IR root is invalid",
    );
  }
  const root = normalized as Record<string, unknown>;
  if (
    root.node !== "Endpoint" ||
    root.name !== requestedEndpoint ||
    typeof root.irVersion !== "string" ||
    root.irVersion.length === 0 ||
    root.irVersion.length > 32 ||
    Object.hasOwn(root, "provenance")
  ) {
    throw new CandidateManifestError(
      "BRAIN_MANIFEST_LIMIT",
      "candidate normalized IR identity is invalid",
    );
  }

  let nodeCount = 0;
  const stack: Array<{ value: unknown; depth: number }> = [
    { value: normalized, depth: 0 },
  ];
  while (stack.length > 0) {
    const current = stack.pop()!;
    nodeCount += 1;
    if (
      nodeCount > MAX_CANDIDATE_IR_NODES ||
      current.depth > MAX_CANDIDATE_IR_DEPTH
    ) {
      throw new CandidateManifestError(
        "BRAIN_MANIFEST_LIMIT",
        "candidate normalized IR exceeds its structure limit",
      );
    }
    if (Array.isArray(current.value)) {
      for (const member of current.value) {
        stack.push({ value: member, depth: current.depth + 1 });
      }
      continue;
    }
    if (current.value !== null && typeof current.value === "object") {
      for (const member of Object.values(
        current.value as Record<string, unknown>,
      )) {
        stack.push({ value: member, depth: current.depth + 1 });
      }
      continue;
    }
    if (
      current.value !== null &&
      typeof current.value !== "string" &&
      typeof current.value !== "boolean" &&
      (typeof current.value !== "number" || !Number.isFinite(current.value))
    ) {
      throw new CandidateManifestError(
        "BRAIN_MANIFEST_LIMIT",
        "candidate normalized IR contains a non-JSON value",
      );
    }
    if (
      typeof current.value === "number" &&
      Number.isInteger(current.value) &&
      !Number.isSafeInteger(current.value)
    ) {
      throw new CandidateManifestError(
        "BRAIN_MANIFEST_LIMIT",
        "candidate normalized IR contains an unsafe integer",
      );
    }
  }
  const canonical = canonicalJson(normalized);
  if (Buffer.byteLength(canonical, "utf8") > MAX_CANDIDATE_IR_BYTES) {
    throw new CandidateManifestError(
      "BRAIN_MANIFEST_LIMIT",
      "candidate normalized IR exceeds its byte limit",
    );
  }
  return JSON.parse(canonical) as unknown;
}

function invalidCandidateCompile(
  code: string,
  message: string,
): Record<string, unknown> {
  return {
    schema_version: 1,
    operation: "compile-candidate",
    status: "invalid",
    diagnostics: [{ file: "", line: 1, code, message }],
    endpoint: null,
    endpoint_sha256: null,
    runtime_context_sha256: null,
    manifest: null,
    manifest_sha256: null,
    ir: null,
    ir_sha256: null,
  };
}

async function compileCandidate(
  tenantRoot: string,
  requestedEndpoint: string,
): Promise<Record<string, unknown>> {
  const docs = await loadTenantDocs(tenantRoot, { validate: true });
  const diagnostics = tenantErrors(docs).slice(0, 128);
  if (diagnostics.length > 0) {
    return {
      ...invalidCandidateCompile(
        "BRAIN_TENANT_INVALID",
        "candidate tenant snapshot is invalid",
      ),
      diagnostics,
    };
  }
  const compiled = compileTenantEndpoints(docs, tenantRoot);
  const endpointSource = compiled.get(requestedEndpoint);
  if (endpointSource === undefined) {
    return invalidCandidateCompile(
      "BRAIN_ENDPOINT_IDENTITY",
      "endpoint strutturale richiesto non compilato",
    );
  }
  try {
    const endpoint = parseIr<IrEndpoint>(endpointSource);
    if (endpoint.node !== "Endpoint" || endpoint.name !== requestedEndpoint) {
      return invalidCandidateCompile(
        "BRAIN_ENDPOINT_IDENTITY",
        "endpoint strutturale richiesto non univoco",
      );
    }
    const manifest = candidateManifest(endpoint, endpointSource);
    const ir = candidateIr(endpoint, requestedEndpoint);
    const runtimeContext = JSON.stringify(buildRuntimeCtx(docs, tenantRoot));
    return {
      schema_version: 1,
      operation: "compile-candidate",
      status: "ok",
      diagnostics: [],
      endpoint: requestedEndpoint,
      endpoint_sha256: sha256(endpointSource),
      runtime_context_sha256: sha256(runtimeContext),
      manifest,
      manifest_sha256: canonicalHash(manifest),
      ir,
      ir_sha256: canonicalHash(ir),
    };
  } catch (error: unknown) {
    if (error instanceof CandidateManifestError) {
      return invalidCandidateCompile(error.code, error.message);
    }
    return invalidCandidateCompile(
      "BRAIN_MANIFEST_INVALID",
      "compiled endpoint cannot be normalized safely",
    );
  }
}

async function compileStructure(
  tenantRoot: string,
  requestedEndpoint: string,
): Promise<Record<string, unknown>> {
  const docs = await loadTenantDocs(tenantRoot, { validate: true });
  const diagnostics = tenantErrors(docs).slice(0, 128);
  if (diagnostics.length > 0) {
    return {
      schema_version: 1,
      operation: "compile-structure",
      status: "invalid",
      diagnostics,
      endpoint: null,
      structural_ir: null,
      structural_sha256: null,
    };
  }
  const compiled = compileTenantEndpoints(docs, tenantRoot);
  const endpointSource = compiled.get(requestedEndpoint);
  if (endpointSource === undefined) {
    return {
      schema_version: 1,
      operation: "compile-structure",
      status: "invalid",
      diagnostics: [
        {
          file: "",
          line: 1,
          code: "BRAIN_ENDPOINT_IDENTITY",
          message: "endpoint strutturale richiesto non compilato",
        },
      ],
      endpoint: null,
      structural_ir: null,
      structural_sha256: null,
    };
  }
  const structuralIr = stripProvenance(JSON.parse(endpointSource));
  const structuralJson = canonicalJson(structuralIr);
  return {
    schema_version: 1,
    operation: "compile-structure",
    status: "ok",
    diagnostics: [],
    endpoint: requestedEndpoint,
    structural_ir: structuralIr,
    structural_sha256: sha256(structuralJson),
  };
}

async function main(): Promise<void> {
  const request = await readRequest();
  const response =
    request.operation === "semantic-catalog"
      ? await semanticCatalog(request.tenant_root)
      : request.operation === "compile"
        ? await compile(request.tenant_root, request.endpoint)
        : request.operation === "compile-candidate"
          ? await compileCandidate(request.tenant_root, request.endpoint)
          : request.operation === "compile-structure"
            ? await compileStructure(request.tenant_root, request.endpoint)
            : request.operation === "edit-surface"
              ? await editSurface(
                  request.tenant_root,
                  request.relative_path,
                  request.endpoint,
                )
              : request.operation === "lossless-inventory"
                ? await losslessInventory(
                    request.tenant_root,
                    request.relative_path,
                    request.endpoint,
                  )
                : await losslessApply(
                    request.tenant_root,
                    request.relative_path,
                    request.endpoint,
                    request.plan,
                  );
  process.stdout.write(`${JSON.stringify(response)}\n`);
}

main().catch((error: unknown) => {
  const message =
    error instanceof Error ? error.message : "unknown runner failure";
  process.stderr.write(`metis-brain runner failed: ${message}\n`);
  process.exitCode = 1;
});
