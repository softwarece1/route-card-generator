/** Annotate "Item 50" / "ITEM NO. 50" mentions with parts-list name + part number (display only). */

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
 * @param {Record<string, object>} itemLookup keyed by item number string
 * @param {number|string} itemNo
 * @returns {{ name: string, partNo: string, label: string }}
 */
export function resolveItemLabel(itemLookup, itemNo) {
  const hit = (itemLookup && itemLookup[String(itemNo)]) || {};
  const name = normalizeInstructionCase(String(hit.description || hit.designation || "").trim());
  const partNo = String(hit.partNumber || hit.part_number || "").trim();
  const bits = [name, partNo].filter(Boolean);
  return {
    name,
    partNo,
    label: bits.join(", "),
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
 * Replace item mentions in instruction text with "Item N (name, partNo)" when PL has a match.
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
 * Format chip / leftover item line: "#50 Name · Part" or "#50" when unknown.
 */
export function formatItemChip(item, itemLookup = {}) {
  const no = item?.itemNo;
  if (no == null) return "";
  const fromItem = {
    description: item.description,
    designation: item.designation,
    partNumber: item.partNumber || item.part_number,
  };
  const hit = itemLookup[String(no)] || {};
  const name = normalizeInstructionCase(
    String(fromItem.description || fromItem.designation || hit.description || hit.designation || "").trim()
  );
  const partNo = String(fromItem.partNumber || hit.partNumber || hit.part_number || "").trim();
  const bits = [name, partNo].filter(Boolean);
  const qty =
    item.qty != null && item.qty !== ""
      ? ` ×${item.qty}`
      : "";
  if (bits.length) return `#${no}${qty} (${bits.join(", ")})`;
  return `#${no}${qty}`;
}
