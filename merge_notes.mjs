#!/usr/bin/env node
// Batch CLI: renders a merged PDF (imported-PDF background + ink + typed
// text, correct color mode) for every note in an export's manifest.json.
//
//   node merge_notes.mjs [--manifest output/manifest.json] [--output-root output]
//                        [--colors auto|light|dark|both]
//
// --colors auto (default): per note, use its own dark_mode_compatibility
//   signal to pick light or dark -- one PDF per note.
// --colors light / dark: force that mode for every note -- one PDF per note.
// --colors both: render BOTH a light and a dark copy for every note, so
//   nothing is decided for you; pick per-note later (or use the web viewer).
//
// Requires: vendor/Samsung_Notes built (npm install && npm run build there).

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { renderNoteToPdf } from "./lib/noteRenderer.mjs";

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith("--")) args[argv[i].slice(2)] = argv[i + 1];
  }
  return args;
}

async function exportOne(sdocxPath, basePath, mode) {
  const bytes = readFileSync(sdocxPath);
  const { pdf, colorMode } = await renderNoteToPdf(bytes, mode);
  const suffix = mode === "both" ? ` (${colorMode})` : "";
  const outPath = `${basePath}${suffix}.pdf`;
  writeFileSync(outPath, pdf);
  return { outPath, colorMode };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const colors = args.colors ?? "auto"; // auto | light | dark | both
  const manifestPath = resolve(args.manifest ?? "output/manifest.json");
  const outputRoot = resolve(args["output-root"] ?? "output");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

  let done = 0, failed = 0, skipped = 0;
  for (const entry of manifest.notes) {
    if (entry.merged_pdfs) { skipped++; continue; }
    const sdocxPath = join(outputRoot, entry.sdocx_file);
    if (!existsSync(sdocxPath)) { failed++; continue; }
    const basePath = sdocxPath.replace(/\.sdocx$/, " (merged)");
    try {
      entry.merged_pdfs = {};
      if (colors === "both") {
        for (const mode of ["light", "dark"]) {
          const { outPath, colorMode } = await exportOne(sdocxPath, basePath, mode);
          entry.merged_pdfs[colorMode] = outPath.slice(outputRoot.length + 1);
        }
      } else {
        const { outPath, colorMode } = await exportOne(sdocxPath, basePath, colors);
        entry.merged_pdfs[colorMode] = outPath.slice(outputRoot.length + 1);
      }
      done++;
      console.log(`  OK   ${entry.title}: ${Object.keys(entry.merged_pdfs).join(", ")}`);
    } catch (err) {
      failed++;
      console.log(`  FAIL ${entry.title}: ${err?.message ?? err}`);
    }
    if ((done + failed) % 20 === 0) writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  }
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  console.log(`\nDone: ${done}, failed: ${failed}, already had merged_pdfs: ${skipped}`);
}

// Only run when invoked directly (`node merge_notes.mjs`), not when imported.
if (process.argv[1] === fileURLToPathSafe(import.meta.url)) {
  main();
}

function fileURLToPathSafe(url) {
  try {
    return new URL(url).pathname;
  } catch {
    return undefined;
  }
}
