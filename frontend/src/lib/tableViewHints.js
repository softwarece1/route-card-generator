/**
 * Parse TABLE / FIGURE / DETAIL / named-block refs for gated drawing crops.
 * Never invents data — only extracts ids + optional sheet/file hints.
 */

import { createElement } from "react";
import { annotateItemMentions } from "@/lib/itemLabels";

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
    const key = `${k}:${id}`;
    const label =
      k === "named"
        ? id
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
 * Render instruction text with PL labels and gated view-ref (i) buttons.
 * No crop → no (i). Never invents.
 *
 * @param {string} text
 * @param {{ itemLookup?: object, viewCrops?: object[], onOpenViewCrop?: (crop: object, el: HTMLElement) => void }} opts
 * @returns {import("react").ReactNode}
 */
export function renderInstructionWithViewInfo(text, opts = {}) {
  const { itemLookup = {}, viewCrops = [], onOpenViewCrop } = opts;
  const annotated = annotateItemMentions(text, itemLookup) || String(text || "");
  if (!annotated) return annotated;

  const nodes = [];
  let last = 0;
  let key = 0;
  VIEW_MENTION_RE.lastIndex = 0;
  let m;
  while ((m = VIEW_MENTION_RE.exec(annotated))) {
    const start = m.index;
    const end = start + m[0].length;
    if (start > last) {
      nodes.push(annotated.slice(last, start));
    }
    nodes.push(annotated.slice(start, end));
    const { kind, refId } = kindFromMention(m[0], m[1], m[2]);
    const crop = findAvailableViewCrop(viewCrops, kind, refId);
    if (crop && typeof onOpenViewCrop === "function") {
      nodes.push(
        createElement(
          "button",
          {
            key: `view-i-${key++}`,
            type: "button",
            className: "instr-view-info-btn",
            title: `View ${crop.label || refId}`,
            "aria-label": `View drawing snapshot for ${crop.label || refId}`,
            onClick: (e) => {
              e.preventDefault();
              e.stopPropagation();
              onOpenViewCrop(crop, e.currentTarget);
            },
            onMouseDown: (e) => e.stopPropagation(),
            onKeyDown: (e) => e.stopPropagation(),
          },
          createElement("i", { className: "pi pi-info-circle", "aria-hidden": true })
        )
      );
    }
    last = end;
  }
  if (last < annotated.length) {
    nodes.push(annotated.slice(last));
  }
  return nodes.length ? nodes : annotated;
}
