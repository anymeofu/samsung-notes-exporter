#!/usr/bin/env node
// Local-only web viewer/exporter for your archived Samsung Notes.
// No external framework (just node:http) to avoid extra dependencies.
//
//   node server.mjs [--output output] [--port 4848]
//
// Open http://localhost:4848 . Everything runs on your machine; nothing is
// sent anywhere. Rendering reuses lib/noteRenderer.mjs (vendor/Samsung_Notes
// + @twango/sdocx WASM), same as merge_notes.mjs.

import { createServer } from "node:http";
import { readFileSync, writeFileSync } from "node:fs";
import { readFile as readFileP } from "node:fs/promises";
import { resolve, join, extname } from "node:path";
import { renderNoteToPdf, suggestColorMode } from "./lib/noteRenderer.mjs";

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith("--")) args[argv[i].slice(2)] = argv[i + 1];
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
const OUTPUT_ROOT = resolve(args.output ?? "output");
const PORT = Number(args.port ?? 4848);
const MANIFEST_PATH = join(OUTPUT_ROOT, "manifest.json");
const STATIC_DIR = resolve("static");

function loadManifest() {
  return JSON.parse(readFileSync(MANIFEST_PATH, "utf8"));
}
function saveManifest(m) {
  writeFileSync(MANIFEST_PATH, JSON.stringify(m, null, 2));
}

function buildTree(manifest) {
  const root = { name: "", folders: {}, notes: [] };
  for (const entry of manifest.notes) {
    const parts = (entry.folder || "").split("/").filter(Boolean);
    let node = root;
    for (const part of parts) {
      node.folders[part] ??= { name: part, folders: {}, notes: [] };
      node = node.folders[part];
    }
    node.notes.push({
      id: entry.id,
      title: entry.title || "(untitled)",
      locked: !!entry.locked,
      hasMergedLight: !!entry.merged_pdfs?.light,
      hasMergedDark: !!entry.merged_pdfs?.dark,
      hasPdfOnly: !entry.pdf_file && !entry.merged_pdfs,
    });
  }
  const toArray = (node) => ({
    name: node.name,
    folders: Object.values(node.folders).map(toArray).sort((a, b) => a.name.localeCompare(b.name)),
    notes: node.notes.sort((a, b) => a.title.localeCompare(b.title)),
  });
  return toArray(root);
}

// Small render cache so toggling light/dark doesn't re-render every click.
const CACHE_LIMIT = 12;
const renderCache = new Map(); // key -> {pdf, colorMode}
function cacheGet(key) {
  const v = renderCache.get(key);
  if (v) { renderCache.delete(key); renderCache.set(key, v); } // LRU bump
  return v;
}
function cacheSet(key, value) {
  renderCache.set(key, value);
  if (renderCache.size > CACHE_LIMIT) {
    renderCache.delete(renderCache.keys().next().value);
  }
}

const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

async function serveStatic(req, res) {
  let path = req.url === "/" ? "/index.html" : req.url;
  path = path.split("?")[0];
  const filePath = join(STATIC_DIR, path);
  if (!filePath.startsWith(STATIC_DIR)) { res.writeHead(403); res.end(); return true; }
  try {
    const data = await readFileP(filePath);
    res.writeHead(200, { "Content-Type": MIME[extname(filePath)] ?? "application/octet-stream" });
    res.end(data);
    return true;
  } catch {
    return false;
  }
}

function json(res, status, obj) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(obj));
}

function findEntry(manifest, id) {
  return manifest.notes.find((n) => n.id === id);
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");

  try {
    if (url.pathname === "/api/tree") {
      const manifest = loadManifest();
      return json(res, 200, buildTree(manifest));
    }

    const previewMatch = url.pathname.match(/^\/api\/note\/([^/]+)\/preview$/);
    if (previewMatch) {
      const id = decodeURIComponent(previewMatch[1]);
      const manifest = loadManifest();
      const entry = findEntry(manifest, id);
      if (!entry) return json(res, 404, { error: "note not found" });
      const mode = url.searchParams.get("mode") ?? "auto";
      const sdocxPath = join(OUTPUT_ROOT, entry.sdocx_file);
      const cacheKey = `${id}:${mode}`;
      let cached = cacheGet(cacheKey);
      if (!cached) {
        const bytes = await readFileP(sdocxPath);
        const { pdf, colorMode } = await renderNoteToPdf(bytes, mode);
        cached = { pdf, colorMode };
        cacheSet(cacheKey, cached);
      }
      res.writeHead(200, { "Content-Type": "application/pdf", "X-Color-Mode": cached.colorMode });
      return res.end(cached.pdf);
    }

    const sdocxMatch = url.pathname.match(/^\/api\/note\/([^/]+)\/sdocx$/);
    if (sdocxMatch) {
      const id = decodeURIComponent(sdocxMatch[1]);
      const manifest = loadManifest();
      const entry = findEntry(manifest, id);
      if (!entry) return json(res, 404, { error: "note not found" });
      const bytes = await readFileP(join(OUTPUT_ROOT, entry.sdocx_file));
      res.writeHead(200, {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": `attachment; filename="${(entry.title || "note").replace(/"/g, "")}.sdocx"`,
        "Access-Control-Allow-Origin": "*",
      });
      return res.end(bytes);
    }

    const suggestMatch = url.pathname.match(/^\/api\/note\/([^/]+)\/suggest$/);
    if (suggestMatch) {
      const id = decodeURIComponent(suggestMatch[1]);
      const manifest = loadManifest();
      const entry = findEntry(manifest, id);
      if (!entry) return json(res, 404, { error: "note not found" });
      const bytes = await readFileP(join(OUTPUT_ROOT, entry.sdocx_file));
      const mode = await suggestColorMode(bytes);
      return json(res, 200, { suggested: mode });
    }

    const exportMatch = url.pathname.match(/^\/api\/note\/([^/]+)\/export$/);
    if (exportMatch && req.method === "POST") {
      const id = decodeURIComponent(exportMatch[1]);
      const manifest = loadManifest();
      const entry = findEntry(manifest, id);
      if (!entry) return json(res, 404, { error: "note not found" });
      const mode = url.searchParams.get("mode") ?? "auto"; // light | dark | both | auto
      const sdocxPath = join(OUTPUT_ROOT, entry.sdocx_file);
      const bytes = await readFileP(sdocxPath);
      const basePath = sdocxPath.replace(/\.sdocx$/, " (merged)");
      const modes = mode === "both" ? ["light", "dark"] : [mode];
      entry.merged_pdfs ??= {};
      const written = [];
      for (const m of modes) {
        const { pdf, colorMode } = await renderNoteToPdf(bytes, m);
        const suffix = modes.length > 1 || m === "both" ? ` (${colorMode})` : "";
        const outPath = `${basePath}${suffix}.pdf`;
        writeFileSync(outPath, pdf);
        entry.merged_pdfs[colorMode] = outPath.slice(OUTPUT_ROOT.length + 1);
        written.push({ colorMode, path: outPath });
      }
      saveManifest(manifest);
      return json(res, 200, { written });
    }

    const served = await serveStatic(req, res);
    if (served) return;

    res.writeHead(404);
    res.end("not found");
  } catch (err) {
    console.error(err);
    json(res, 500, { error: String(err?.message ?? err) });
  }
});

server.listen(PORT, () => {
  console.log(`Samsung Notes viewer: http://localhost:${PORT}`);
  console.log(`Archive: ${OUTPUT_ROOT}`);
});
