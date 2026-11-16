/** Annotate "Item 50" / "ITEM NO. 50" mentions with parts-list name + part number (display only). */

import { normalizeInstructionCase } from "@/lib/instructionCase";

const ITEM_MENTION =
  /(?:ITEMS?|ITMS?|IT\.?)\s*(?:NO\.?|NOS\.?|NUMBER|#)?\s*-?\s*(\d{1,3})\b/gi;

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
 * Replace item mentions in instruction text with "Item N (name, partNo)" when PL has a match.
 * Display-only — normalizes OCR caps first, then appends PL identity.
 * @param {string} text
 * @param {Record<string, object>} itemLookup
 * @returns {string}
 */
export function annotateItemMentions(text, itemLookup = {}) {
  const raw = normalizeInstructionCase(String(text || ""));
  if (!raw) return "";
  return raw.replace(ITEM_MENTION, (full, num) => {
    const { label } = resolveItemLabel(itemLookup, num);
    if (!label) return full;
    // Preserve original token shape, append identity in brackets once.
    if (/\([^)]*\)\s*$/.test(full)) return full;
    return `${full} (${label})`;
  });
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
