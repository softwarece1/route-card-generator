const KEY = "rc_vlm_page_indexes";

/** @returns {number[]} 1-based page indexes; empty = Auto (all allowed pages) */
export function getVlmPageIndexes() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr
      .map((n) => Number(n))
      .filter((n) => Number.isInteger(n) && n >= 1 && n <= 24);
  } catch {
    return [];
  }
}

export function setVlmPageIndexes(pages) {
  const next = Array.isArray(pages)
    ? pages
        .map((n) => Number(n))
        .filter((n) => Number.isInteger(n) && n >= 1 && n <= 24)
    : [];
  localStorage.setItem(KEY, JSON.stringify(next));
}
