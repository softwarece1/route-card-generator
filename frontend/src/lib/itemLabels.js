/** Annotate "Item 50" / "ITEM NO. 50" mentions with the parts-list name only (display only). */

import { normalizeInstructionCase } from "@/lib/instructionCase";

/** Head of an item mention: Item / Items / ITM + optional No. + first number. */
const ITEM_HEAD =
  /(?:ITEMS?|ITMS?|IT\.?)\s*(?:NO\.?|NOS\.?|NUMBER|#)?\s*-?\s*(\d{1,4})\b/gi;

/**
 * Continuation after the first number: ", 30" / "& 3" / "and 30" / "/ 40".
 * Does not require repeating "Item".
 */
const ITEM_LIST_CONT = /^\s*(?:,|&|\/|and)\s*(\d{1,4})\b/i;

/**
 * PL stores items as 4-digit (0010); GA balloons use short form (10, 60, 450).
 * Match on numeric value — try unpadded + zero-padded keys.
 * @param {Record<string, object>|null|undefined} itemLookup
 * @param {number|string} itemNo
 * @returns {object}
 */
export function lookupPlItem(itemLookup, itemNo) {
  if (!itemLookup || itemNo == null || itemNo === "") return {};
  const raw = String(itemNo).trim();
  if (itemLookup[raw]) return itemLookup[raw];
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return {};
  const unpadded = String(Math.trunc(n));
  const padded = unpadded.padStart(4, "0");
  return itemLookup[unpadded] || itemLookup[padded] || itemLookup[String(n)] || {};
}

/**
 * @param {Record<string, object>} itemLookup keyed by item number string (60 and/or 0060)
 * @param {number|string} itemNo
 * @returns {{ name: string, partNo: string, label: string }}
 */
export function resolveItemLabel(itemLookup, itemNo) {
  const hit = lookupPlItem(itemLookup, itemNo);
  const name = normalizeInstructionCase(String(hit.description || hit.designation || "").trim());
  const partNo = String(hit.partNumber || hit.part_number || "").trim();
  return {
    name,
    partNo,
    label: name,
  };
}

/**
 * Walk text and yield each item-number span, including list tails:
 * "Item 2 & 3", "Item 20 and 30", "Item 110, 120, 130, 140".
 * @param {string} text already case-normalized preferred
 * @returns {{ start: number, end: number, num: string }[]}
 */
export function findItemMentionSpans(text) {
  const raw = String(text || "");
  const spans = [];
  const re = new RegExp(ITEM_HEAD.source, "gi");
  let m;
  while ((m = re.exec(raw))) {
    spans.push({ start: m.index, end: m.index + m[0].length, num: m[1] });
    let cursor = m.index + m[0].length;
    while (true) {
      const cont = raw.slice(cursor).match(ITEM_LIST_CONT);
      if (!cont) break;
      const start = cursor;
      const end = cursor + cont[0].length;
      spans.push({ start, end, num: cont[1] });
      cursor = end;
    }
    re.lastIndex = cursor;
  }
  return spans;
}

/**
 * Collect item numbers mentioned in text (including list continuations).
 * @param {string} text
 * @returns {Set<string|number>}
 */
export function collectMentionedItemNos(text) {
  const set = new Set();
  const normalized = normalizeInstructionCase(String(text || ""));
  for (const span of findItemMentionSpans(normalized)) {
    set.add(span.num);
    const n = Number(span.num);
    if (!Number.isNaN(n)) set.add(n);
  }
  return set;
}

/**
 * Replace item mentions in instruction text with "Item N (name)" when PL has a match.
 * Display-only — normalizes OCR caps first, then appends PL identity for every number in a list.
 * @param {string} text
 * @param {Record<string, object>} itemLookup
 * @returns {string}
 */
export function annotateItemMentions(text, itemLookup = {}) {
  const raw = normalizeInstructionCase(String(text || ""));
  if (!raw) return "";
  const spans = findItemMentionSpans(raw);
  if (!spans.length) return raw;

  let out = "";
  let last = 0;
  for (const span of spans) {
    out += raw.slice(last, span.start);
    const chunk = raw.slice(span.start, span.end);
    const { label } = resolveItemLabel(itemLookup, span.num);
    // Skip if this span already ends with a parenthetical (e.g. prior annotate)
    if (label && !/\([^)]*\)\s*$/.test(chunk)) {
      // Also skip if immediately followed by an existing " (…)" from a previous pass
      const after = raw.slice(span.end);
      if (/^\s*\([^)]*\)/.test(after)) {
        out += chunk;
      } else {
        out += `${chunk} (${label})`;
      }
    } else {
      out += chunk;
    }
    last = span.end;
  }
  out += raw.slice(last);
  return out;
}

/**
 * Format chip / leftover item line: "#50 ×qty (Name) · partNo" or "#50" when unknown.
 */
export function formatItemChip(item, itemLookup = {}) {
  const no = item?.itemNo;
  if (no == null) return "";
  // GA / ops chips use short form (60), not PL padding (0060)
  const n = Number(no);
  const displayNo = Number.isFinite(n) && n > 0 ? String(Math.trunc(n)) : String(no);
  const fromItem = {
    description: item.description,
    designation: item.designation,
    partNumber: item.partNumber || item.part_number,
  };
  const hit = lookupPlItem(itemLookup, no);
  const name = normalizeInstructionCase(
    String(
      fromItem.description || fromItem.designation || hit.description || hit.designation || "",
    ).trim(),
  );
  const partNo = String(
    fromItem.partNumber || hit.partNumber || hit.part_number || "",
  ).trim();
  const qty =
    item.qty != null && item.qty !== ""
      ? ` ×${item.qty}`
      : "";
  if (name && partNo) return `#${displayNo}${qty} (${name}) · ${partNo}`;
  if (name) return `#${displayNo}${qty} (${name})`;
  if (partNo) return `#${displayNo}${qty} · ${partNo}`;
  return `#${displayNo}${qty}`;
}
