// Reusable note-rendering core, shared by the CLI batch exporter and the
// local web viewer/server. Renders a .sdocx's pages (ink + typed text +
// composited imported-PDF background) into a single PDF, in an explicitly
// chosen color mode ("light" | "dark" | "auto" -> detected per note).
//
// Built on the vendored vendor/Samsung_Notes project's own rendering code
// (same approach their Inkport viewer and MCP connector use), plus the
// @twango/sdocx WASM parser both this project and sdocx-cli are built on.

import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { randomUUID } from "node:crypto";

const HERE = dirname(fileURLToPath(import.meta.url));
const VENDOR = join(HERE, "..", "vendor", "Samsung_Notes");

let wasmReady;
let DocumentSession;
let readNoteDetails, drawPaper;
let buildPdf;
let renderPdfPage;
let Resvg;
let jpeg;
let readZipAttachment;

async function ensureLoaded() {
  if (wasmReady) return wasmReady;
  wasmReady = (async () => {
    ({ DocumentSession } = await import(join(VENDOR, "node_modules", "@twango", "sdocx", "sdocx.js")));
    const { initSync } = await import(join(VENDOR, "node_modules", "@twango", "sdocx", "sdocx.js"));
    initSync({ module: readFileSync(join(VENDOR, "node_modules", "@twango", "sdocx", "sdocx_bg.wasm")) });
    ({ readNoteDetails, drawPaper } = await import(join(VENDOR, "dist", "core", "note.js")));
    ({ buildPdf } = await import(join(VENDOR, "dist", "core", "pdfWriter.js")));
    ({ renderPdfPage } = await import(join(VENDOR, "dist", "pdf.js")));
    ({ Resvg } = await import(join(VENDOR, "node_modules", "@resvg", "resvg-js", "index.js")));
    jpeg = (await import(join(VENDOR, "node_modules", "jpeg-js", "index.js"))).default;
    ({ readZipAttachment } = await import(join(VENDOR, "dist", "core", "zip.js")));
  })();
  return wasmReady;
}

const PAGE_PIXEL_WIDTH = 1600;
const JPEG_QUALITY = 85;

async function withSession(bytes, use) {
  await ensureLoaded();
  const session = new DocumentSession(bytes);
  try {
    return await use(session);
  } finally {
    session.free();
  }
}

// The library's own dark canvas is #252525 (dark gray, matching Samsung
// Notes' authoring page color), not black. Force a true black page to match
// the app's actual dark-theme look -- only the page background rect (the
// first <rect> right after <svg ...>), so ink/shape colors that happen to
// use a similar gray elsewhere are left untouched.
//
// Tried and reverted: rendering always in "light" mode and manually
// recoloring default-ink text/strokes for a dark display. That broke
// highlighter/marker strokes, which use multiply-blend compositing assuming
// a white backdrop -- paint black behind them and multiply makes them
// vanish (anything x black = black). The parser's own "dark" render_svg
// path evidently accounts for this; ours didn't. Keep using it directly.
function toDarkCanvas(svg) {
  return svg.replace(
    /^(\s*<svg\b[^>]*>\s*<rect\b[^>]*fill=")#[0-9a-fA-F]{6}("[^>]*\/>)/,
    '$1#000000$2',
  );
}

// Highlighter/marker strokes are composited via mix-blend-mode (darken in
// light mode, lighten in dark mode) in their own <g style="mix-blend-mode:
// ...">...</g> batch, drawn after ordinary ink. That blend math only
// reliably preserves legibility for near-black (light mode) or near-white
// (dark mode) underlying ink -- confirmed on a real note: a highlighter
// over mid-tone colored ink (teal-green `#3f8881` under yellow `#ffcb30`)
// renders fully opaque, hiding the text, in BOTH light and dark mode alike
// (so this isn't gated on colorMode). Replacing the blend-mode with plain
// reduced opacity is less visually "correct" for the cases that already
// worked (a touch paler than the real app), but guarantees legibility
// regardless of underlying color, which matters more for an archive.
function fixHighlighterOpacity(svg) {
  return svg.replace(
    /<g style="mix-blend-mode:(?:darken|lighten)">/g,
    '<g style="opacity:0.5">',
  );
}

function rasterizeToJpeg(svg, width, colorMode) {
  const rendered = new Resvg(svg, {
    fitTo: { mode: "width", value: width },
    background: colorMode === "dark" ? "black" : "white",
    font: { loadSystemFonts: true },
  }).render();
  const jpegBytes = jpeg.encode(
    { width: rendered.width, height: rendered.height, data: rendered.pixels },
    JPEG_QUALITY,
  ).data;
  return { jpeg: jpegBytes, width: rendered.width, height: rendered.height };
}

// dark_mode_compatibility isn't in note.ts's typed Inspection interface, but
// is present in the raw session.inspection() JSON (sdocx-wasm's
// DocumentMetadata). This is a SIGNAL, not a forced choice -- callers decide
// whether to use it.
function detectedColorMode(inspection) {
  const compat = inspection?.document?.metadata?.dark_mode_compatibility;
  return compat === true ? "dark" : "light";
}

// The parser's own content_bbox undercounts in practice (seen: reports
// y_max=1352 while real strokes/objects go to y_max=1994 on the same page)
// -- so don't trust it alone for "how tall is this page's real content".
// Walk every object's own bbox fields directly and take the true max, on
// both axes (content can run off the right edge just as easily as the
// bottom).
function maxObjectExtent(page) {
  let maxX = -Infinity;
  let maxY = -Infinity;
  const visit = (node) => {
    if (node === null || typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const item of node) visit(item);
      return;
    }
    if (typeof node.y_max === "number" && typeof node.y_min === "number" && typeof node.x_max === "number") {
      if (node.y_max > maxY) maxY = node.y_max;
      if (node.x_max > maxX) maxX = node.x_max;
    }
    for (const key in node) visit(node[key]);
  };
  visit(page?.objects);
  return {
    maxX: maxX === -Infinity ? undefined : maxX,
    maxY: maxY === -Infinity ? undefined : maxY,
  };
}

// The renderer's own stated page size (used for the SVG's viewBox/width/
// height, and separately for the background <rect>'s own width/height)
// comes straight from Samsung's stored per-page metadata, and in practice
// that sometimes undershoots where the page's actual objects are placed --
// real content past it gets silently clipped out of every rendered
// page/PDF/image (verified: content invisible in Acrobat, in Inkport's own
// "PDF view", and in a raw resvg render alike). The SVG markup for that
// content IS already present, just outside the declared bounds -- so
// widening the canvas to cover it is enough; nothing needs to be redrawn.
//
// Both the outer <svg> AND the background <rect> need widening: the first
// render (viewBox/width/height only) left the background rect at its
// original, smaller size, which left the newly-revealed strip with no
// paint at all -- transparent in a raw SVG, which showed as a stray white
// block in Inkport's card view (<img src="blob:...">, no canvas fill
// behind it, unlike the PDF-export path which happens to paint a full
// canvas background first and masked the same gap).
const CLIP_MARGIN = 24;

// Order-independent: replaces width="N" and height="N" within one element's
// own attribute list, wherever they fall (observed order is actually
// height-then-width, not the other way round -- don't assume either).
function setWidthHeight(tag, width, height) {
  return tag
    .replace(/\bwidth="[\d.]+"/, `width="${width}"`)
    .replace(/\bheight="[\d.]+"/, `height="${height}"`);
}

function extendForClippedContent(svg, page) {
  const { maxX, maxY } = maxObjectExtent(page);
  if (maxX === undefined && maxY === undefined) return svg;
  const viewBoxMatch = svg.match(/viewBox="([\d.\-]+) ([\d.\-]+) ([\d.\-]+) ([\d.\-]+)"/);
  if (!viewBoxMatch) return svg;
  const [, vx, vy, vw, vh] = viewBoxMatch;
  const declaredWidth = parseFloat(vw);
  const declaredHeight = parseFloat(vh);
  const neededWidth = maxX === undefined ? declaredWidth : Math.max(declaredWidth, Math.ceil(maxX + CLIP_MARGIN));
  const neededHeight = maxY === undefined ? declaredHeight : Math.max(declaredHeight, Math.ceil(maxY + CLIP_MARGIN));
  if (neededWidth <= declaredWidth && neededHeight <= declaredHeight) return svg;

  // Work on a header substring only, split at a complete-tag boundary (never
  // mid-tag, which would corrupt the XML): the header is
  //   <svg height="H" viewBox="0 0 W H" width="W" ...>
  //   <rect fill="#.." height="H" width="W" x="0" y="0"/>
  //   <defs><clipPath id="..."><rect height="H" width="W" x="0" y="0"/></clipPath></defs>
  // and we split right after "</defs>" if it appears early (bounded search,
  // so a `</defs>` far later in the document -- unrelated to this preamble
  // -- is never matched). If that exact shape isn't found, fall back to
  // only the very first <svg> tag and very first <rect/> tag, via targeted
  // regexes that can't straddle a tag boundary either way.
  const SEARCH_WINDOW = 2000;
  const defsEnd = svg.slice(0, SEARCH_WINDOW).indexOf("</defs>");
  if (defsEnd !== -1) {
    const splitAt = defsEnd + "</defs>".length;
    let header = svg.slice(0, splitAt);
    const rest = svg.slice(splitAt);
    header = header.replace(/<svg\b[^>]*>/, (tag) => setWidthHeight(tag, neededWidth, neededHeight));
    header = header.replace(/<rect\b[^>]*\/>/g, (tag) => setWidthHeight(tag, neededWidth, neededHeight));
    header = header.replace(
      /viewBox="[\d.\-]+ [\d.\-]+ [\d.\-]+ [\d.\-]+"/,
      `viewBox="${vx} ${vy} ${neededWidth}.0 ${neededHeight}.0"`,
    );
    return header + rest;
  }

  let out = svg.replace(/<svg\b[^>]*>/, (tag) => setWidthHeight(tag, neededWidth, neededHeight));
  out = out.replace(/^(\s*<svg\b[^>]*>\s*)<rect\b[^>]*\/>/, (whole, prefix) => {
    const rectTag = whole.slice(prefix.length);
    return prefix + setWidthHeight(rectTag, neededWidth, neededHeight);
  });
  out = out.replace(
    /viewBox="[\d.\-]+ [\d.\-]+ [\d.\-]+ [\d.\-]+"/,
    `viewBox="${vx} ${vy} ${neededWidth}.0 ${neededHeight}.0"`,
  );
  return out;
}

// Image formats the underlying renderer already draws correctly on its own.
// Anything else (notably .heic from modern phone cameras) is silently
// dropped by the renderer ("UnresolvedImageMedia" in sdocx-cli's diagnostics)
// even though the bytes are fully present in the .sdocx -- so we decode and
// composite those ourselves instead of leaving a blank spot on the page.
const NATIVELY_SUPPORTED_EXT = new Set(["jpg", "jpeg", "png", "gif", "webp", "bmp"]);

function convertToJpegDataUri(bytes, ext) {
  const stamp = randomUUID();
  const inPath = join(tmpdir(), `sn-img-${stamp}.${ext}`);
  const outPath = join(tmpdir(), `sn-img-${stamp}.jpg`);
  writeFileSync(inPath, bytes);
  try {
    // sips (macOS built-in) decodes HEIC/HEIF natively; this project already
    // assumes macOS (Parallels) elsewhere, so no new dependency is added.
    execFileSync("sips", ["-s", "format", "jpeg", inPath, "--out", outPath], { stdio: "pipe" });
    const jpegBytes = readFileSync(outPath);
    return `data:image/jpeg;base64,${jpegBytes.toString("base64")}`;
  } finally {
    try { unlinkSync(inPath); } catch {}
    try { unlinkSync(outPath); } catch {}
  }
}

function pageFor(inspection, pageIndex) {
  const { document, layout } = inspection;
  const sourcePageIndex = layout.pages[pageIndex].source_page_index;
  return document.pages[sourcePageIndex];
}

// Finds PlacedImage objects on this page whose media the renderer can't
// decode, with their on-page bounding box, so we can draw them ourselves.
function unsupportedPlacedImages(inspection, page, sdocxBytes) {
  const mediaEntries = inspection.document.metadata.media_manifest?.entries ?? [];
  const overlays = [];
  for (const obj of page?.objects ?? []) {
    const placed = obj?.content?.Element?.PlacedImage;
    if (!placed) continue;
    const entry = mediaEntries.find((e) => e.bind_id === placed.media_id);
    if (!entry) continue;
    const ext = entry.file_name.split(".").pop()?.toLowerCase() ?? "";
    if (NATIVELY_SUPPORTED_EXT.has(ext)) continue;
    const mediaBytes = readZipAttachment(sdocxBytes, entry.file_name);
    if (!mediaBytes) continue;
    let dataUri;
    try {
      dataUri = convertToJpegDataUri(mediaBytes, ext);
    } catch {
      continue; // e.g. sips not available on this OS -- leave the spot blank rather than crash the export
    }
    const { x_min, y_min, x_max, y_max } = placed.bbox;
    overlays.push({ dataUri, x: x_min, y: y_min, width: x_max - x_min, height: y_max - y_min });
  }
  return overlays;
}

// Inserts <image> elements for unsupported-format photos right after the
// page background rect -- same stacking convention as drawPaper (photo as
// base layer, any ink/annotations drawn later in the SVG land on top).
function drawUnsupportedImages(svg, overlays) {
  if (!overlays.length) return svg;
  const tags = overlays
    .map(({ dataUri, x, y, width, height }) => `<image x="${x}" y="${y}" width="${width}" height="${height}" preserveAspectRatio="none" href="${dataUri}"/>`)
    .join("");
  const replaced = svg.replace(/^(\s*<svg\b[^>]*>\s*<rect\b[^>]*\/>)/, `$1${tags}`);
  return replaced === svg ? svg : replaced; // if the regex didn't match, leave svg untouched rather than silently drop content
}

function svgPaperInfo(inspection, page) {
  const { note_text, media_manifest } = inspection.document.metadata;
  const records = page?.background?.pdf_paper ?? [];
  const paper = records.map((record) => {
    const file = media_manifest?.entries?.find((e) => e.bind_id === record.media_id)?.file_name;
    const [left, top, right, bottom] = Object.values(record.rectangle)[0];
    return { file, pageIndex: record.page_index, x: left, y: top, width: right - left, height: bottom - top };
  });
  if (paper.length || note_text?.text?.trim() || note_text?.object_spans?.length) {
    return { paper };
  }
  return { inkBottom: page?.content_bbox?.y_max, paper };
}

/** Returns "light" or "dark": what this note's own metadata suggests, without rendering anything. */
export async function suggestColorMode(sdocxBytes) {
  return withSession(sdocxBytes, async (session) => detectedColorMode(session.inspection()));
}

/**
 * Renders a note to a PDF buffer.
 * @param {Buffer} sdocxBytes
 * @param {"light"|"dark"|"auto"} colorMode  "auto" uses this note's own dark_mode_compatibility signal.
 * @returns {Promise<{pdf: Buffer, pages: number, colorMode: "light"|"dark", title: string}>}
 */
export async function renderNoteToPdf(sdocxBytes, colorMode = "auto") {
  return withSession(sdocxBytes, async (session) => {
    const details = readNoteDetails(session, sdocxBytes);
    const inspection = session.inspection();
    const resolvedMode = colorMode === "auto" ? detectedColorMode(inspection) : colorMode;
    const images = [];
    for (let i = 0; i < details.pageCount; i++) {
      const page = pageFor(inspection, i);
      const rawSvg = session.render_svg(i, resolvedMode);
      let svg = resolvedMode === "dark" ? toDarkCanvas(rawSvg) : rawSvg;
      svg = fixHighlighterOpacity(svg);
      svg = extendForClippedContent(svg, page);
      const overlays = unsupportedPlacedImages(inspection, page, sdocxBytes);
      svg = drawUnsupportedImages(svg, overlays);
      const rendered = { svg, ...svgPaperInfo(inspection, page) };
      let withPaper;
      try {
        withPaper = await drawPaper(rendered, sdocxBytes, PAGE_PIXEL_WIDTH, renderPdfPage);
      } catch {
        withPaper = svg; // fall back to ink-only if the embedded PDF page can't be rendered (e.g. oversized)
      }
      const { jpeg: jpegBytes, width, height } = rasterizeToJpeg(withPaper, PAGE_PIXEL_WIDTH, resolvedMode);
      images.push({ jpeg: jpegBytes, width, height });
    }
    if (!images.length) throw new Error("note has no pages");
    const pdf = Buffer.from(
      buildPdf(images, { title: details.title, createdMs: details.createdMs, modifiedMs: details.modifiedMs }),
    );
    return { pdf, pages: images.length, colorMode: resolvedMode, title: details.title };
  });
}
