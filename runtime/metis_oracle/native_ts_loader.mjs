import { writeSync } from "node:fs";
import { access, readFile, realpath } from "node:fs/promises";
import { stripTypeScriptTypes } from "node:module";
import { isAbsolute, relative, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const TYPESCRIPT_SUFFIXES = [".ts", ".mts", ".cts"];
const CAPSULE_ROOT = await realpath(fileURLToPath(new URL("../", import.meta.url)));
const TRACE_FD_ENV = "METIS_MODEL1_NATIVE_TRACE_FD";

function optionalTraceFd() {
  const raw = process.env[TRACE_FD_ENV];
  if (raw === undefined) return null;
  if (!/^[0-9]+$/.test(raw)) throw blocked("trace descriptor is not numeric");
  const descriptor = Number(raw);
  if (!Number.isSafeInteger(descriptor) || descriptor < 3) {
    throw blocked("trace descriptor is outside the inherited descriptor range");
  }
  return descriptor;
}

const TRACE_FD = optionalTraceFd();

function blocked(message) {
  const error = new Error(`native loader blocked: ${message}`);
  error.code = "ERR_METIS_NATIVE_LOADER_BLOCKED";
  return error;
}

function insideCapsule(path) {
  const offset = relative(CAPSULE_ROOT, path);
  return offset === "" || (!offset.startsWith(`..${sep}`) && offset !== ".." && !isAbsolute(offset));
}

async function rosteredFileUrl(url, label) {
  if (!(url instanceof URL) || url.protocol !== "file:") {
    throw blocked(`${label} is not a file URL`);
  }
  let path;
  try {
    path = await realpath(fileURLToPath(url));
  } catch (error) {
    throw blocked(`${label} is unavailable: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!insideCapsule(path)) throw blocked(`${label} escapes the sealed capsule`);
  return pathToFileURL(path).href;
}

async function existingTypeScriptCandidate(specifier, parentURL) {
  if (!parentURL || !specifier.startsWith(".") || !specifier.endsWith(".js")) return null;
  const base = new URL(specifier, parentURL);
  for (const suffix of TYPESCRIPT_SUFFIXES) {
    const candidate = new URL(`${base.href.slice(0, -3)}${suffix}`);
    try {
      await access(candidate);
      return await rosteredFileUrl(candidate, "TypeScript candidate");
    } catch (error) {
      if (error?.code === "ERR_METIS_NATIVE_LOADER_BLOCKED") throw error;
    }
  }
  return null;
}

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("node:")) return nextResolve(specifier, context);
  let resolved;
  try {
    resolved = await nextResolve(specifier, context);
  } catch (error) {
    const candidate = await existingTypeScriptCandidate(specifier, context.parentURL);
    if (candidate === null) throw error;
    return { format: "module", shortCircuit: true, url: candidate };
  }
  if (resolved.url.startsWith("node:")) return resolved;
  if (!resolved.url.startsWith("file:")) throw blocked("non-file module schemes are forbidden");
  return { ...resolved, url: await rosteredFileUrl(new URL(resolved.url), "resolved module") };
}

export async function load(url, context, nextLoad) {
  if (url.startsWith("node:")) return nextLoad(url, context);
  const sealedUrl = await rosteredFileUrl(new URL(url), "loaded module");
  let result;
  if (!TYPESCRIPT_SUFFIXES.some((suffix) => sealedUrl.endsWith(suffix))) {
    result = await nextLoad(sealedUrl, context);
  } else {
    const source = await readFile(new URL(sealedUrl), "utf8");
    result = {
      format: "module",
      shortCircuit: true,
      source: stripTypeScriptTypes(source, {
        mode: "transform",
        sourceMap: false,
        sourceUrl: sealedUrl,
      }),
    };
  }
  if (TRACE_FD !== null) writeSync(TRACE_FD, `${JSON.stringify(sealedUrl)}\n`);
  return result;
}
