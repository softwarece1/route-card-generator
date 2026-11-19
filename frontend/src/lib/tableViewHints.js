/**
 * Parse TABLE references from operator instructions / viewRefs for gated crops.
 * Never invents data — only extracts ids + optional sheet/file hints.
 */

const TABLE_OPEN = /Open\s+TABLE\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;
const TABLE_FOLLOW = /(?:Follow|Use|See|as\s+per)\s+TABLE\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;
const TABLE_PLAIN = /\bTABLE\s*(?:NO\.?\s*)?([0-9]{1,2}|[A-Z])\b/gi;
const SHEET_NEAR = /sheet\s*(?:no\.?\s*)?([0-9]{1,2})\b/i;
const FILE_NEAR = /file\s+['"]([^'"]+)['"]/i;

/**
 * @param {string} text
 * @param {object[]} [viewRefs]
 * @returns {{ tableId: string, label: string, sheet: number|null, filename: string, drawingId: number|null }[]}
 */
export function collectTableViewHints(text, viewRefs = []) {
  const out = new Map();

  const add = (tableId, extra = {}) => {
    const id = String(tableId || "")
      .trim()
      .toUpperCase();
    if (!id) return;
    const key = id;
    const prev = out.get(key) || {
      tableId: id,
      label: `TABLE ${id}`,
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
    if (String(vr.kind || "").toLowerCase() !== "table") continue;
    const id = vr.id || String(vr.label || "").replace(/^TABLE\s*/i, "");
    add(id, {
      sheet: vr.matchedSheet != null ? Number(vr.matchedSheet) : null,
      filename: vr.matchedFilename || "",
      drawingId: vr.matchedDrawingId != null ? Number(vr.matchedDrawingId) : null,
    });
  }

  const raw = String(text || "");
  if (raw.trim()) {
    for (const re of [TABLE_OPEN, TABLE_FOLLOW, TABLE_PLAIN]) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(raw))) {
        const id = m[1];
        const window = raw.slice(Math.max(0, m.index - 20), m.index + 160);
        const sheetM = SHEET_NEAR.exec(window);
        const fileM = FILE_NEAR.exec(window);
        add(id, {
          sheet: sheetM ? Number(sheetM[1]) : null,
          filename: fileM ? fileM[1] : "",
        });
      }
    }
  }

  return [...out.values()];
}

/**
 * Resolve a drawing id from session drawings / docs using hint filename.
 * @param {{ tableId: string, filename?: string, drawingId?: number|null }} hint
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
