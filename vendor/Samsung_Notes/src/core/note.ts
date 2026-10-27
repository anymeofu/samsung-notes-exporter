import { unzipSync } from "fflate";
import { viewBox } from "./svg.js";
import { readZipAttachment } from "./zip.js";

export interface TextSpan {
  object_type: string;
  text_index_utf16: number;
  content?: Record<string, unknown>;
}

export interface NoteDetails {
  title: string;
  rawText: string;
  spans: TextSpan[];
  createdMs: number | null;
  modifiedMs: number | null;
  pageCount: number;
  inkPages: number[];
}

export interface RenderedPage {
  svg: string;
  inkBottom?: number;
  paper: PaperPlacement[];
}

// A page of a PDF the note was made from, and where it lies on the note's page.
export interface PaperPlacement {
  file: string;
  pageIndex: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

export type ColorMode = "light" | "dark";

// The parts of the parser's DocumentSession used here, so Node and the browser can load the WASM their own way.
export interface NoteSession {
  inspection(): unknown;
  render_svg(pageIndex: number, colorMode: ColorMode): string;
  readonly page_count: number;
}

// Saved as left, top, right, bottom; older notes store floats, newer ones integers.
interface PdfPaper {
  media_id: number;
  page_index: number;
  rectangle: Record<string, [number, number, number, number]>;
}

interface InspectedPage {
  objects?: unknown[];
  content_bbox?: { y_max: number };
  background?: { pdf_paper?: PdfPaper[] };
}

interface Inspection {
  document: {
    pages: InspectedPage[];
    metadata: {
      note_title?: { text?: string };
      note_text?: { text?: string; object_spans?: TextSpan[] };
      created_ms?: number;
      modified_ms?: number;
      media_manifest?: { entries: { bind_id: number; file_name: string }[] };
      dark_mode_compatibility?: boolean;
    };
  };
  layout: { pages: { source_page_index: number }[] };
}

// A real .sdocx carries its dates in a tail appended after the zip. Re-zipping drops that tail, and
// the parser then returns microsecond values labelled as ms. end_tag.bin holds both dates in
// microseconds (undocumented layout, checked on the public fixtures); anything unexpected gives null.
const END_TAG = "end_tag.bin";
const END_TAG_MODIFIED_US = 8;
const END_TAG_CREATED_US = 46;
const U64_BYTES = 8;
const EARLIEST_DATE_MS = Date.UTC(2000, 0, 1);
const ONE_DAY_MS = 86_400_000;

function endTagDates(bytes: Uint8Array): { createdMs: number; modifiedMs: number } | undefined {
  const tag = unzipSync(bytes, { filter: (file) => file.name === END_TAG })[END_TAG];
  if (!tag || tag.length < END_TAG_CREATED_US + U64_BYTES) return undefined;
  const view = new DataView(tag.buffer, tag.byteOffset, tag.byteLength);
  const ms = (at: number) => Math.round(Number(view.getBigUint64(at, true)) / 1000);
  return { createdMs: ms(END_TAG_CREATED_US), modifiedMs: ms(END_TAG_MODIFIED_US) };
}

const plausibleDate = (ms: number | undefined): number | null =>
  ms !== undefined && ms >= EARLIEST_DATE_MS && ms <= Date.now() + ONE_DAY_MS ? ms : null;

export function readNoteDetails(session: NoteSession, bytes: Uint8Array): NoteDetails {
  const { document, layout } = session.inspection() as Inspection;
  const { metadata } = document;
  const dates = endTagDates(bytes);
  return {
    title: metadata.note_title?.text ?? "",
    rawText: metadata.note_text?.text ?? "",
    spans: metadata.note_text?.object_spans ?? [],
    createdMs: plausibleDate(dates ? dates.createdMs : metadata.created_ms),
    modifiedMs: plausibleDate(dates ? dates.modifiedMs : metadata.modified_ms),
    pageCount: session.page_count,
    inkPages: layout.pages.flatMap(({ source_page_index }, i) => (hasInk(document.pages[source_page_index]) ? [i + 1] : [])),
  };
}

const hasInk = (page: InspectedPage | undefined): boolean => (page?.objects?.length ?? 0) > 0;

// What this note's own metadata suggests ("dark_mode_compatibility"): a
// SIGNAL for a caller's default, never a forced choice.
export function suggestedColorMode(session: NoteSession): ColorMode {
  const { document } = session.inspection() as Inspection;
  return document.metadata.dark_mode_compatibility === true ? "dark" : "light";
}

// The parser's own "dark" canvas is #252525 (dark gray, Samsung Notes' actual
// authoring page color), not black. Swap just the page-background rect (the
// first <rect> right after <svg ...>) to true black, to match the app's
// dark-theme look, leaving any ink/shape color that happens to be a similar
// gray elsewhere untouched.
//
// Tried and reverted: rendering always in "light" mode and manually
// recoloring default-ink text/strokes for a dark display. That broke
// highlighter/marker strokes, which use multiply-blend compositing assuming
// a white backdrop -- paint black behind them and multiply makes them
// vanish (anything x black = black). render_svg(index, "dark") evidently
// accounts for this; our own post-process didn't. Keep using it directly.
function toDarkCanvas(svg: string): string {
  return svg.replace(/^(\s*<svg\b[^>]*>\s*<rect\b[^>]*fill=")#[0-9a-fA-F]{6}("[^>]*\/>)/, "$1#000000$2");
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
function fixHighlighterOpacity(svg: string): string {
  return svg.replace(/<g style="mix-blend-mode:(?:darken|lighten)">/g, '<g style="opacity:0.5">');
}

// The parser's own content_bbox undercounts in practice (seen: reports
// y_max=1352 while real strokes/objects go to y_max=1994 on the same page)
// -- so don't trust it alone for "how tall is this page's real content".
// Walk every object's own bbox fields directly and take the true max, on
// both axes (content can run off the right edge just as easily as the
// bottom).
function maxObjectExtent(page: InspectedPage | undefined): { maxX?: number; maxY?: number } {
  let maxX = -Infinity;
  let maxY = -Infinity;
  const visit = (node: unknown): void => {
    if (node === null || typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const item of node) visit(item);
      return;
    }
    const record = node as Record<string, unknown>;
    if (typeof record.y_max === "number" && typeof record.y_min === "number" && typeof record.x_max === "number") {
      if (record.y_max > maxY) maxY = record.y_max;
      if (record.x_max > maxX) maxX = record.x_max;
    }
    for (const key in record) visit(record[key]);
  };
  visit(page?.objects);
  return {
    maxX: maxX === -Infinity ? undefined : maxX,
    maxY: maxY === -Infinity ? undefined : maxY,
  };
}

// The renderer's own stated page size (the SVG's viewBox/width/height, and
// separately the background <rect>'s own width/height) comes straight from
// Samsung's stored per-page metadata, and in practice that sometimes
// undershoots where the page's actual objects are placed -- real content
// past it gets silently clipped out of every rendered page/PDF/image. The
// SVG markup for that content IS already present, just outside the declared
// bounds -- widening the canvas to cover it is enough; nothing needs to be
// redrawn.
//
// Both the outer <svg> AND the background <rect> need widening: widening
// only the outer tag leaves the background rect at its original, smaller
// size, so the newly-revealed strip has no paint at all -- transparent in a
// raw SVG, which shows as a stray white block in Inkport's card view
// (<img src="blob:...">, no canvas fill behind it, unlike the PDF-export
// path, which happens to paint a full canvas background first and so
// masked the same gap in testing).
const CLIP_MARGIN = 24;

// Order-independent: replaces width="N" and height="N" within one element's
// own attribute list, wherever they fall (observed order is actually
// height-then-width, not the other way round -- don't assume either).
function setWidthHeight(tag: string, width: number, height: number): string {
  return tag.replace(/\bwidth="[\d.]+"/, `width="${width}"`).replace(/\bheight="[\d.]+"/, `height="${height}"`);
}

function extendForClippedContent(svg: string, page: InspectedPage | undefined): string {
  const { maxX, maxY } = maxObjectExtent(page);
  if (maxX === undefined && maxY === undefined) return svg;
  const viewBoxMatch = svg.match(/viewBox="([\d.-]+) ([\d.-]+) ([\d.-]+) ([\d.-]+)"/);
  if (!viewBoxMatch) return svg;
  const [, vx, vy, vw, vh] = viewBoxMatch as unknown as [string, string, string, string, string];
  const declaredWidth = parseFloat(vw);
  const declaredHeight = parseFloat(vh);
  const neededWidth = maxX === undefined ? declaredWidth : Math.max(declaredWidth, Math.ceil(maxX + CLIP_MARGIN));
  const neededHeight = maxY === undefined ? declaredHeight : Math.max(declaredHeight, Math.ceil(maxY + CLIP_MARGIN));
  if (neededWidth <= declaredWidth && neededHeight <= declaredHeight) return svg;

  // Work on a header substring only, split at a complete-tag boundary
  // (never mid-tag, which would corrupt the XML) -- see
  // lib/noteRenderer.mjs's copy of this function for the full rationale and
  // the exact preamble shape being matched.
  const SEARCH_WINDOW = 2000;
  const defsEnd = svg.slice(0, SEARCH_WINDOW).indexOf("</defs>");
  if (defsEnd !== -1) {
    const splitAt = defsEnd + "</defs>".length;
    let header = svg.slice(0, splitAt);
    const rest = svg.slice(splitAt);
    header = header.replace(/<svg\b[^>]*>/, (tag) => setWidthHeight(tag, neededWidth, neededHeight));
    header = header.replace(/<rect\b[^>]*\/>/g, (tag) => setWidthHeight(tag, neededWidth, neededHeight));
    header = header.replace(
      /viewBox="[\d.-]+ [\d.-]+ [\d.-]+ [\d.-]+"/,
      `viewBox="${vx} ${vy} ${neededWidth}.0 ${neededHeight}.0"`,
    );
    return header + rest;
  }

  let out = svg.replace(/<svg\b[^>]*>/, (tag) => setWidthHeight(tag, neededWidth, neededHeight));
  out = out.replace(/^(\s*<svg\b[^>]*>\s*)<rect\b[^>]*\/>/, (whole, prefix: string) => {
    const rectTag = whole.slice(prefix.length);
    return prefix + setWidthHeight(rectTag, neededWidth, neededHeight);
  });
  out = out.replace(
    /viewBox="[\d.-]+ [\d.-]+ [\d.-]+ [\d.-]+"/,
    `viewBox="${vx} ${vy} ${neededWidth}.0 ${neededHeight}.0"`,
  );
  return out;
}

// content_bbox bounds strokes and shapes only, so it marks the page's real end only when the note has no typed text,
// objects or PDF pages. It also undercounts in practice (see
// maxObjectExtent above) -- cropToInk (web/src/library.ts, used for pages
// tall enough to need multiple print sheets) uses this inkBottom value as
// its crop boundary, so a page we just widened via extendForClippedContent
// could otherwise get re-cropped right back down by a stale content_bbox.
// Use the same reliable true-extent value here too, falling back to
// content_bbox only if no object bbox was found at all.
export function readPageSvg(session: NoteSession, pageIndex: number, colorMode: ColorMode = "light"): RenderedPage {
  const rawSvg = session.render_svg(pageIndex, colorMode);
  let svg = colorMode === "dark" ? toDarkCanvas(rawSvg) : rawSvg;
  svg = fixHighlighterOpacity(svg);
  const { document, layout } = session.inspection() as Inspection;
  const { note_text, media_manifest } = document.metadata;
  const page = document.pages[layout.pages[pageIndex]!.source_page_index];
  svg = extendForClippedContent(svg, page);
  const paper = (page?.background?.pdf_paper ?? []).map((record) => placePaper(record, media_manifest?.entries ?? []));
  if (paper.length || note_text?.text?.trim() || note_text?.object_spans?.length) return { svg, paper };
  return { svg, inkBottom: maxObjectExtent(page).maxY ?? page?.content_bbox?.y_max, paper };
}

// Draws one PDF page as an image URL (a data: URL) the page's SVG can embed, pixelWidth pixels wide.
export type PdfPageRenderer = (pdf: Uint8Array, pageIndex: number, pixelWidth: number) => Promise<string>;

// The parser leaves out the PDF pages a note was made from, so they're drawn here: over the paper, under the ink.
export async function drawPaper(page: RenderedPage, sdocx: Uint8Array, pixelWidth: number, render: PdfPageRenderer): Promise<string> {
  if (!page.paper.length) return page.svg;
  const scale = pixelWidth / (viewBox(page.svg)?.width ?? pixelWidth);
  let images = "";
  for (const { file, pageIndex, x, y, width, height } of page.paper) {
    const pdf = readZipAttachment(sdocx, file);
    if (!pdf) throw new Error(`The note's PDF “${file}” is missing.`);
    const href = await render(pdf, pageIndex, Math.round(width * scale));
    images += `<image x="${x}" y="${y}" width="${width}" height="${height}" preserveAspectRatio="none" href="${href}"/>`;
  }
  const svg = page.svg.replace(PAPER, (paper) => paper + images);
  if (svg === page.svg) throw new Error("The page has no paper to draw its PDF on.");
  return svg;
}

const PAPER = /^\s*<svg\b[^>]*>\s*<rect\b[^>]*\/>/;

function placePaper(record: PdfPaper, media: { bind_id: number; file_name: string }[]): PaperPlacement {
  const file = media.find((entry) => entry.bind_id === record.media_id)?.file_name;
  if (!file) throw new Error(`The note's PDF (media ${record.media_id}) is missing from its file list.`);
  const [left, top, right, bottom] = Object.values(record.rectangle)[0]!;
  return { file, pageIndex: record.page_index, x: left, y: top, width: right - left, height: bottom - top };
}
