/**
 * Parse / link shared reference sheets (PS200, DS10, …) against a folder catalog.
 */

import { createElement } from "react";
import { annotateItemMentions } from "@/lib/itemLabels";

const MENTION_RE = /\b([A-Za-z]{1,6})\s*[-_]?\s*(\d{2,6})\b/g;

export function normalizeFolderCode(raw) {
  return String(raw || "")
    .replace(/[^A-Za-z]/g, "")
    .toUpperCase()
    .slice(0, 6);
}

export function canonicalRefCode(folderCode, digits) {
  const fc = normalizeFolderCode(folderCode);
  const n = parseInt(String(digits || "").replace(/\D/g, ""), 10);
  if (!fc || Number.isNaN(n)) return null;
  return `${fc}${n}`;
}

/**
 * @param {string} text
 * @param {Iterable<string>} folderCodes
 * @returns {string[]} unique canonical codes in encounter order
 */
export function extractRefCandidateCodes(text, folderCodes = []) {
  const known = new Set(
    [...folderCodes].map(normalizeFolderCode).filter(Boolean),
  );
  if (!known.size || !text) return [];
  const found = [];
  const seen = new Set();
  MENTION_RE.lastIndex = 0;
  let m;
  const src = String(text);
  while ((m = MENTION_RE.exec(src))) {
    const code = canonicalRefCode(m[1], m[2]);
    const prefix = normalizeFolderCode(m[1]);
    if (!code || !known.has(prefix) || seen.has(code)) continue;
    seen.add(code);
    found.push(code);
  }
  return found;
}

/**
 * @param {object[]} foundRows resolve API `found` array
 * @returns {Record<string, object>}
 */
export function indexFoundRefDocs(foundRows = []) {
  const map = {};
  for (const row of foundRows || []) {
    if (row?.code) map[row.code] = row;
  }
  return map;
}

/**
 * Render text with PL annotations + clickable ref-doc links when found.
 * Unresolved mentions stay plain text.
 *
 * @param {string} text
 * @param {{
 *   itemLookup?: object,
 *   foundByCode?: Record<string, object>,
 *   onOpenRefDoc?: (row: object, el?: HTMLElement) => void,
 * }} opts
 * @returns {import("react").ReactNode}
 */
export function renderTextWithRefDocLinks(text, opts = {}) {
  const { itemLookup = {}, foundByCode = {}, onOpenRefDoc } = opts;
  const annotated = annotateItemMentions(text, itemLookup) || String(text || "");
  if (!annotated) return annotated;

  const knownCodes = Object.keys(foundByCode || {});
  if (!knownCodes.length || typeof onOpenRefDoc !== "function") {
    return annotated;
  }

  const nodes = [];
  let last = 0;
  let key = 0;
  MENTION_RE.lastIndex = 0;
  let m;
  while ((m = MENTION_RE.exec(annotated))) {
    const code = canonicalRefCode(m[1], m[2]);
    const row = code ? foundByCode[code] : null;
    const start = m.index;
    const end = start + m[0].length;
    if (start > last) nodes.push(annotated.slice(last, start));
    if (row) {
      nodes.push(
        createElement(
          "button",
          {
            key: `ref-${key++}`,
            type: "button",
            className: "rca-refdoc-link",
            title: `Open ${row.code || code}`,
            "aria-label": `Open reference sheet ${row.code || code}`,
            onClick: (e) => {
              e.preventDefault();
              e.stopPropagation();
              onOpenRefDoc(row, e.currentTarget);
            },
            onMouseDown: (e) => e.stopPropagation(),
          },
          annotated.slice(start, end),
        ),
      );
    } else {
      nodes.push(annotated.slice(start, end));
    }
    last = end;
  }
  if (last < annotated.length) nodes.push(annotated.slice(last));
  return nodes.length ? nodes : annotated;
}
