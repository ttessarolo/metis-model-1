import { readFileSync } from "node:fs";
import { dirname, posix } from "node:path";
import { pathToFileURL } from "node:url";

function fail(message) {
  throw new Error(`native evidence census blocked: ${message}`);
}

function exactObject(value, keys, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail(`${label} is not an object`);
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) fail(`${label} keys are not exact`);
  return value;
}

function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}

function safePath(value, label) {
  if (typeof value !== "string" || value.length === 0 || value.startsWith("/") || value.includes("\\")) {
    fail(`${label} is not a relative POSIX path`);
  }
  const normalized = posix.normalize(value);
  if (normalized !== value || normalized === ".." || normalized.startsWith("../")) {
    fail(`${label} is not canonical`);
  }
  return value;
}

function importIsTypeOnly(ts, node) {
  if (ts.isImportDeclaration(node)) {
    const clause = node.importClause;
    if (!clause) return false;
    if (clause.isTypeOnly) return true;
    const bindings = clause.namedBindings;
    return bindings && ts.isNamedImports(bindings) && bindings.elements.length > 0
      && bindings.elements.every((element) => element.isTypeOnly);
  }
  if (ts.isExportDeclaration(node)) {
    if (node.isTypeOnly) return true;
    return node.exportClause && ts.isNamedExports(node.exportClause) && node.exportClause.elements.length > 0
      && node.exportClause.elements.every((element) => element.isTypeOnly);
  }
  return false;
}

function resolveRelative(parent, specifier, available) {
  const base = posix.normalize(posix.join(dirname(parent), specifier));
  const candidates = [];
  if (/\.(?:js|mjs|cjs)$/.test(base)) {
    const stem = base.replace(/\.(?:js|mjs|cjs)$/, "");
    candidates.push(`${stem}.ts`, `${stem}.mts`, `${stem}.cts`, `${stem}.tsx`);
  } else if (/\.(?:ts|mts|cts|tsx)$/.test(base)) {
    candidates.push(base);
  } else {
    candidates.push(`${base}.ts`, `${base}.mts`, `${base}.cts`, `${base}.tsx`);
    candidates.push(
      posix.join(base, "index.ts"),
      posix.join(base, "index.mts"),
      posix.join(base, "index.cts"),
      posix.join(base, "index.tsx"),
    );
  }
  const matches = candidates.filter((candidate) => available.has(candidate));
  if (matches.length !== 1) fail(`relative import ${specifier} from ${parent} resolved ${matches.length} times`);
  return matches[0];
}

async function main() {
  let input;
  try {
    input = JSON.parse(readFileSync(0, "utf8"));
  } catch {
    fail("stdin is not JSON");
  }
  exactObject(input, ["entries", "files", "parser_path"], "request");
  if (!Array.isArray(input.entries) || !Array.isArray(input.files)) fail("entries/files are not arrays");
  const parserPath = safePath(input.parser_path, "parser path");
  const parserUrl = pathToFileURL(posix.resolve(process.cwd(), parserPath));
  const ts = await import(parserUrl.href);
  if (typeof ts.createSourceFile !== "function") fail("registered TypeScript parser API is unavailable");

  const sources = new Map();
  for (const [index, raw] of input.files.entries()) {
    const row = exactObject(raw, ["path", "source"], `file ${index}`);
    const path = safePath(row.path, `file ${index} path`);
    if (typeof row.source !== "string" || sources.has(path)) fail(`file ${index} is invalid or duplicated`);
    sources.set(path, row.source);
  }
  const entries = input.entries.map((entry, index) => safePath(entry, `entry ${index}`));
  if (entries.length === 0 || new Set(entries).size !== entries.length || entries.some((entry) => !sources.has(entry))) {
    fail("entry roster is empty, duplicated or missing");
  }

  const visited = new Set();
  const queue = [...entries].sort();
  const rows = [];
  while (queue.length > 0) {
    const path = queue.shift();
    if (visited.has(path)) continue;
    visited.add(path);
    const source = sources.get(path);
    const sourceFile = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    const imports = [];
    function addImport(specifier, typeOnly, dynamic) {
      if (typeof specifier !== "string" || specifier.length === 0) fail(`non-literal import in ${path}`);
      const relative = specifier.startsWith(".");
      const resolved_path = relative ? resolveRelative(path, specifier, sources) : null;
      imports.push({ dynamic, resolved_path, specifier, type_only: Boolean(typeOnly) });
      if (resolved_path !== null && !visited.has(resolved_path)) queue.push(resolved_path);
    }
    function walk(node) {
      if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier) {
        if (!ts.isStringLiteralLike(node.moduleSpecifier)) fail(`non-literal static import in ${path}`);
        addImport(node.moduleSpecifier.text, importIsTypeOnly(ts, node), false);
      } else if (
        ts.isImportEqualsDeclaration(node)
        && ts.isExternalModuleReference(node.moduleReference)
        && node.moduleReference.expression
      ) {
        if (!ts.isStringLiteralLike(node.moduleReference.expression)) fail(`non-literal import-equals in ${path}`);
        addImport(node.moduleReference.expression.text, node.isTypeOnly, false);
      } else if (
        ts.isCallExpression(node)
        && node.expression.kind === ts.SyntaxKind.ImportKeyword
        && node.arguments.length === 1
      ) {
        if (!ts.isStringLiteralLike(node.arguments[0])) fail(`non-literal dynamic import in ${path}`);
        addImport(node.arguments[0].text, false, true);
      }
      ts.forEachChild(node, walk);
    }
    walk(sourceFile);
    imports.sort((left, right) => canonical(left).localeCompare(canonical(right)));
    rows.push({ imports, path });
    queue.sort();
  }
  rows.sort((left, right) => left.path.localeCompare(right.path));
  process.stdout.write(`${canonical({ entries: [...entries].sort(), rows })}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 2;
});
