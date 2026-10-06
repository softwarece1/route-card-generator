import * as XLSX from "xlsx";

/** Max workbook sheets shown in the in-app viewer (3–5 page budget). */
export const EXCEL_PREVIEW_MAX_SHEETS = 5;

/** Max data rows per sheet (plus header) to keep the UI responsive. */
export const EXCEL_PREVIEW_MAX_ROWS = 200;

export function isExcelFilename(nameOrType = "") {
  const t = String(nameOrType || "").toLowerCase();
  return (
    t.endsWith(".xlsx") ||
    t.endsWith(".xls") ||
    t.endsWith(".xlsm") ||
    t.includes("spreadsheet") ||
    t.includes("excel") ||
    t.includes("sheet")
  );
}

/**
 * Parse an Excel Blob/ArrayBuffer into a capped sheet preview.
 * @returns {{
 *   sheetNames: string[],
 *   sheets: Record<string, { columns: {field:string,header:string}[], rows: object[] }>,
 *   totalSheets: number,
 *   truncatedSheets: boolean,
 *   maxRows: number,
 * }}
 */
export async function parseExcelPreview(source, { maxSheets = EXCEL_PREVIEW_MAX_SHEETS, maxRows = EXCEL_PREVIEW_MAX_ROWS } = {}) {
  let data;
  if (source instanceof ArrayBuffer) {
    data = source;
  } else if (source instanceof Blob) {
    data = await source.arrayBuffer();
  } else {
    throw new Error("Excel preview needs a file Blob or ArrayBuffer");
  }

  const wb = XLSX.read(data, { type: "array", cellDates: true });
  const allNames = wb.SheetNames || [];
  const sheetNames = allNames.slice(0, Math.max(1, Math.min(maxSheets, 5)));
  const sheets = {};

  for (const name of sheetNames) {
    const ws = wb.Sheets[name];
    const matrix = XLSX.utils.sheet_to_json(ws, {
      header: 1,
      defval: "",
      raw: false,
      blankrows: false,
    });
    const headerRow = Array.isArray(matrix[0]) ? matrix[0] : [];
    const body = matrix.slice(1, 1 + maxRows);

    const colCount = Math.max(
      headerRow.length,
      ...body.map((r) => (Array.isArray(r) ? r.length : 0)),
      1,
    );

    const columns = [];
    for (let i = 0; i < colCount; i++) {
      const label = String(headerRow[i] ?? "").trim() || `Column ${i + 1}`;
      columns.push({ field: `c${i}`, header: label });
    }

    const rows = body.map((row, idx) => {
      const obj = { __rowKey: idx };
      for (let i = 0; i < colCount; i++) {
        const v = Array.isArray(row) ? row[i] : "";
        obj[`c${i}`] = v == null ? "" : String(v);
      }
      return obj;
    });

    sheets[name] = { columns, rows };
  }

  return {
    sheetNames,
    sheets,
    totalSheets: allNames.length,
    truncatedSheets: allNames.length > sheetNames.length,
    maxRows,
  };
}

export function triggerBlobDownload(blob, filename) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename || "download.xlsx";
  a.click();
  URL.revokeObjectURL(href);
}
