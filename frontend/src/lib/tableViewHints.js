/**
 * Parse TABLE / FIGURE / DETAIL / named-block refs for gated drawing crops.
 * Never invents data — only extracts ids + optional sheet/file hints.
 */

import { createElement } from "react";
import { annotateItemMentions } from "@/lib/itemLabels";
import { canonicalRefCode } from "@/lib/refDocLinks";

const REF_DOC_MENTION_RE = /\b([A-Za-z]{1,6})\s*[-_]?\s*(\d{2,6})\b/g;

const TABLE_OPEN = /Open\s+TABLE\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;
const TABLE_FOLLOW = /(?:Follow|Use|See|as\s+per)\s+TABLE\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;
const TABLE_PLAIN = /\bTABLE\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;

const FIGURE_OPEN = /Open\s+FIGURE\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;
const FIGURE_FOLLOW =
  /(?:Follow|Use|See|as\s+per|as\s+indicated(?:\s+in)?|as\s+shown(?:\s+in)?)\s+(?:FIGURE|FIG\.?)\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;
const FIGURE_PLAIN = /\b(?:FIGURE|FIG\.?)\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;

const DETAIL_OPEN = /(?:Use|Open|See)\s+DETAIL\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;
const DETAIL_FOLLOW =
  /(?:as\s+indicated(?:\s+in)?|as\s+shown(?:\s+in)?|as\s+per)\s+DETAIL\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;
const DETAIL_PLAIN = /\bDETAIL\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;

const NAMED_BLOCK =
  /\b((?:INTERCONNECTION|INTERCONNECT(?:ION)?)\s+(?:TABLE|LIST(?:ING)?|DETAILS?)|TOOLING\s+MATRIX)\b/gi;

/** Caption printed under the isometric view on GA sheets. */
export const ISO_CAPTION = "ISOMETRIC VIEW";
/** Op text that may need the isometric reference (filtered further by calloutItems). */
const ISO_CUE_RE = /\bITEMS?\s*(?:NO\.?|NOS\.?|#)?\s*\d|\bAS\s+SHOWN\b|\bISOMETRIC\b/i;

const ISO_EXPLICIT_RE = /\bISOMETRIC\b/i;
const ISO_AS_SHOWN_RE = /\bAS\s+SHOWN\b/i;
const ISO_NON_VISUAL_OP_RE =
  /\b(kit|kitting|pack|packing|dispatch|store|stores|issue|incoming|final\s+inspection|qa|qc|test|testing|continuity|hi-?pot|burn-?in)\b/i;
const ITEM_MENTION_GROUP_RE =
  /\bITEMS?\s*(?:NO\.?|NOS\.?|#)?\s*(\d{1,2}(?:\s*(?:,|&|\/|\band\b)\s*\d{1,2})*)/gi;

/** Extract item numbers explicitly referenced in an operation instruction (from notes). */
export function extractReferencedItemNumbers(text) {
  const out = new Set();
  const raw = String(text || "");
  ITEM_MENTION_GROUP_RE.lastIndex = 0;
  let m;
  while ((m = ITEM_MENTION_GROUP_RE.exec(raw))) {
    const nums = m[1].match(/\d{1,2}/g) || [];
    for (const n of nums) {
      const val = Number(n);
      if (val > 0 && val < 100) out.add(val);
    }
  }
  return out;
}

/**
 * Decide whether the GA ISOMETRIC VIEW crop is actually relevant for this operation.
 * - Explicit "ISOMETRIC" mention -> always show.
 * - Kitting / packing / testing / inspection ops -> skip.
 * - When the crop reports calloutItems (balloon numbers visible in the isometric view),
 *   show ONLY if the instruction references at least one of those items.
 * - When calloutItems is empty (e.g. non-text balloons), require "AS SHOWN".
 */
export function shouldShowIsometricCrop(text, calloutItems = [], opName = "") {
  const raw = String(text || "");
  if (ISO_EXPLICIT_RE.test(raw)) return true;
  if (opName && ISO_NON_VISUAL_OP_RE.test(String(opName))) return false;
  const callouts = Array.isArray(calloutItems)
    ? calloutItems.map((n) => Number(n)).filter((n) => Number.isFinite(n) && n > 0)
    : [];
  if (callouts.length > 0) {
    const mentioned = extractReferencedItemNumbers(raw);
    return callouts.some((n) => mentioned.has(n));
  }
  return ISO_AS_SHOWN_RE.test(raw);
}

const SHEET_NEAR = /sheet\s*(?:no\.?\s*)?([0-9]{1,2})\b/i;
const FILE_NEAR = /file\s+['"]([^'"]+)['"]/i;

function namedKey(raw) {
  const u = String(raw || "")
    .replace(/\s+/g, " ")
    .trim()
    .toUpperCase();
  if (u.includes("INTERCONNECT")) return "INTERCONNECTION TABLE";
  if (u.includes("TOOLING") || u.includes("CONNECTORISATION")) return "TOOLING MATRIX";
  return u;
}

/**
 * @param {string} text
 * @param {object[]} [viewRefs]
 * @returns {{ kind: string, refId: string, label: string, sheet: number|null, filename: string, drawingId: number|null }[]}
 */
export function collectViewCropHints(text, viewRefs = []) {
  const out = new Map();

  const add = (kind, refId, extra = {}) => {
    const k = String(kind || "table").toLowerCase();
    let id = String(refId || "").trim();
    if (k === "named") id = namedKey(id);
    else id = id.toUpperCase();
    if (!id) return;
    if (k === "isometric") id = ISO_CAPTION;
    const key = `${k}:${id}`;
    const label =
      k === "named"
        ? id
        : k === "isometric"
          ? ISO_CAPTION
          : k === "figure"
            ? `FIGURE ${id}`
            : k === "detail"
              ? `DETAIL ${id}`
              : `TABLE ${id}`;
    const prev = out.get(key) || {
      kind: k,
      refId: id,
      tableId: k === "table" ? id : undefined,
      label,
      sheet: null,
      filename: "",
      drawingId: null,
    };
    out.set(key, {
      ...prev,
      sheet: extra.sheet ?? prev.sheet,
      filename: extra.filename || prev.filename,
      drawingId: extra.drawingId ?? prev.drawingId,
    });
  };

  for (const vr of viewRefs || []) {
    if (!vr || typeof vr !== "object") continue;
    const kind = String(vr.kind || "").toLowerCase();
    if (!["table", "figure", "detail", "named"].includes(kind)) continue;
    const id =
      vr.id ||
      String(vr.label || "")
        .replace(/^(?:TABLE|FIGURE|DETAIL)\s*/i, "")
        .trim();
    add(kind, kind === "named" ? vr.label || id : id, {
      sheet: vr.matchedSheet != null ? Number(vr.matchedSheet) : null,
      filename: vr.matchedFilename || "",
      drawingId: vr.matchedDrawingId != null ? Number(vr.matchedDrawingId) : null,
    });
  }

  const raw = String(text || "");
  if (!raw.trim()) return [...out.values()];

  const scan = (kind, patterns) => {
    for (const re of patterns) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(raw))) {
        const id = m[1];
        const window = raw.slice(Math.max(0, m.index - 20), m.index + 180);
        const sheetM = SHEET_NEAR.exec(window);
        const fileM = FILE_NEAR.exec(window);
        add(kind, id, {
          sheet: sheetM ? Number(sheetM[1]) : null,
          filename: fileM ? fileM[1] : "",
        });
      }
    }
  };

  scan("table", [TABLE_OPEN, TABLE_FOLLOW, TABLE_PLAIN]);
  scan("figure", [FIGURE_OPEN, FIGURE_FOLLOW, FIGURE_PLAIN]);
  scan("detail", [DETAIL_OPEN, DETAIL_FOLLOW, DETAIL_PLAIN]);

  NAMED_BLOCK.lastIndex = 0;
  let nm;
  while ((nm = NAMED_BLOCK.exec(raw))) {
    const window = raw.slice(Math.max(0, nm.index - 20), nm.index + 200);
    const sheetM = SHEET_NEAR.exec(window);
    const fileM = FILE_NEAR.exec(window);
    add("named", nm[1], {
      sheet: sheetM ? Number(sheetM[1]) : null,
      filename: fileM ? fileM[1] : "",
    });
  }

  // ISOMETRIC VIEW reference: item callouts, "as shown", or explicit isometric wording.
  if (ISO_CUE_RE.test(raw)) add("isometric", ISO_CAPTION, {});

  return [...out.values()];
}

/** @deprecated use collectViewCropHints */
export function collectTableViewHints(text, viewRefs = []) {
  return collectViewCropHints(text, viewRefs).filter((h) => h.kind === "table");
}

/**
 * Resolve a drawing id from session drawings / docs using hint filename.
 * @param {{ filename?: string, drawingId?: number|null }} hint
 * @param {object[]} drawings
 */
export function resolveDrawingIdForTableHint(hint, drawings = []) {
  if (hint?.drawingId) return Number(hint.drawingId);
  const want = String(hint?.filename || "")
    .trim()
    .toLowerCase();
  if (!want || !drawings?.length) return null;
  const norm = (s) =>
    String(s || "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  const exact = drawings.find((d) => norm(d.filename || d.name) === norm(want));
  if (exact?.id) return Number(exact.id);
  const loose = drawings.find((d) => {
    const fn = norm(d.filename || d.name);
    return fn.includes(norm(want)) || norm(want).includes(fn);
  });
  return loose?.id ? Number(loose.id) : null;
}

export const resolveDrawingIdForViewHint = resolveDrawingIdForTableHint;

/** Mentions that can receive an inline (i) when a gated crop exists. */
const VIEW_MENTION_RE =
  /\b(?:(?:FIGURE|FIG\.?|TABLE|DETAIL)\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])|((?:INTERCONNECTION|INTERCONNECT(?:ION)?)\s+(?:TABLE|LIST(?:ING)?|DETAILS?)|TOOLING\s+MATRIX))\b/gi;

/**
 * @param {object[]} crops
 * @param {string} kind
 * @param {string} refId
 */
export function findAvailableViewCrop(crops, kind, refId) {
  const k = String(kind || "").toLowerCase();
  const id = String(refId || "")
    .trim()
    .toUpperCase();
  if (!k || !id || !crops?.length) return null;
  return (
    crops.find((c) => {
      if (!c?.src && !c?.imageBase64) return false;
      if (String(c.kind || "").toLowerCase() !== k) return false;
      const cid = String(c.refId || c.tableId || "")
        .trim()
        .toUpperCase();
      return cid === id || (k === "named" && namedKey(c.label || cid) === namedKey(id));
    }) || null
  );
}

function kindFromMention(fullMatch, idGroup, namedGroup) {
  if (namedGroup) return { kind: "named", refId: namedKey(namedGroup) };
  const head = String(fullMatch || "").toUpperCase();
  if (head.startsWith("FIG")) return { kind: "figure", refId: String(idGroup || "").toUpperCase() };
  if (head.startsWith("DETAIL")) return { kind: "detail", refId: String(idGroup || "").toUpperCase() };
  return { kind: "table", refId: String(idGroup || "").toUpperCase() };
}

/**
 * Render instruction text with PL labels, gated view-ref (i) buttons,
 * and clickable reference-sheet links when found in the library.
 *
 * @param {string} text
 * @param {{
 *   itemLookup?: object,
 *   viewCrops?: object[],
 *   onOpenViewCrop?: (crop: object, el: HTMLElement) => void,
 *   foundByCode?: Record<string, object>,
 *   onOpenRefDoc?: (row: object, el?: HTMLElement) => void,
 * }} opts
 * @returns {import("react").ReactNode}
 */
export function renderInstructionWithViewInfo(text, opts = {}) {
  const {
    itemLookup = {},
    viewCrops = [],
    onOpenViewCrop,
    foundByCode = {},
    onOpenRefDoc,
  } = opts;
  const annotated = annotateItemMentions(text, itemLookup) || String(text || "");
  if (!annotated) return annotated;

  /** @type {{ start: number, end: number, kind: string, payload: object }[]} */
  const spans = [];

  VIEW_MENTION_RE.lastIndex = 0;
  let m;
  while ((m = VIEW_MENTION_RE.exec(annotated))) {
    const { kind, refId } = kindFromMention(m[0], m[1], m[2]);
    const crop = findAvailableViewCrop(viewCrops, kind, refId);
    spans.push({
      start: m.index,
      end: m.index + m[0].length,
      kind: "view",
      payload: { text: m[0], crop },
    });
  }

  if (foundByCode && Object.keys(foundByCode).length && typeof onOpenRefDoc === "function") {
    REF_DOC_MENTION_RE.lastIndex = 0;
    while ((m = REF_DOC_MENTION_RE.exec(annotated))) {
      const code = canonicalRefCode(m[1], m[2]);
      const row = code ? foundByCode[code] : null;
      if (!row) continue;
      spans.push({
        start: m.index,
        end: m.index + m[0].length,
        kind: "ref",
        payload: { text: m[0], row },
      });
    }
  }

  spans.sort((a, b) => a.start - b.start || b.end - a.end);

  const nodes = [];
  let last = 0;
  let key = 0;
  for (const span of spans) {
    if (span.start < last) continue; // overlap — keep earlier/longer
    if (span.start > last) nodes.push(annotated.slice(last, span.start));
    if (span.kind === "ref") {
      const { text: label, row } = span.payload;
      nodes.push(
        createElement(
          "button",
          {
            key: `ref-${key++}`,
            type: "button",
            className: "rca-refdoc-link",
            title: `Open ${row.code || label}`,
            "aria-label": `Open reference sheet ${row.code || label}`,
            onClick: (e) => {
              e.preventDefault();
              e.stopPropagation();
              onOpenRefDoc(row, e.currentTarget);
            },
            onMouseDown: (e) => e.stopPropagation(),
            onKeyDown: (e) => e.stopPropagation(),
          },
          label,
        ),
      );
    } else {
      const { text: label, crop } = span.payload;
      nodes.push(label);
      if (crop && typeof onOpenViewCrop === "function") {
        nodes.push(
          createElement(
            "button",
            {
              key: `view-i-${key++}`,
              type: "button",
              className: "instr-view-info-btn",
              title: `View ${crop.label || label}`,
              "aria-label": `View drawing snapshot for ${crop.label || label}`,
              onClick: (e) => {
                e.preventDefault();
                e.stopPropagation();
                onOpenViewCrop(crop, e.currentTarget);
              },
              onMouseDown: (e) => e.stopPropagation(),
              onKeyDown: (e) => e.stopPropagation(),
            },
            createElement("i", { className: "pi pi-info-circle", "aria-hidden": true }),
          ),
        );
      }
    }
    last = span.end;
  }
  if (last < annotated.length) nodes.push(annotated.slice(last));
  return nodes.length ? nodes : annotated;
}
