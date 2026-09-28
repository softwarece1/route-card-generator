/**
 * OARC print — BEL "OARC/OAMC & Shop Order Details" layout in Rubik.
 *
 * Uses HTML tables (not space-padded monospace) so Rubik columns align.
 * Unknown fields stay blank. Prints via a hidden iframe (no new tab);
 * document title becomes the suggested "Save as PDF" filename.
 */

function s(v) {
  return v == null ? "" : String(v).trim();
}

function num(v, fallback = 0) {
  if (v == null || v === "") return fallback;
  const n = typeof v === "number" ? v : Number(String(v).replace(/,/g, ""));
  return Number.isFinite(n) ? n : fallback;
}

function esc(text) {
  return s(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** 10 → "0010" like the SAP spool */
function opNo4(v) {
  return String(num(v, 0)).padStart(4, "0");
}

function qty3(v) {
  return num(v, 0).toFixed(3);
}

function hrs(v) {
  const n = num(v, 0);
  return Number.isInteger(n) ? n.toFixed(1) : String(n);
}

function today() {
  const d = new Date();
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
}

/** Pull Rubik @font-face rules already loaded by the app (@fontsource). */
function collectRubikCss() {
  const chunks = [];
  for (const sheet of Array.from(document.styleSheets || [])) {
    try {
      for (const rule of Array.from(sheet.cssRules || [])) {
        const text = rule.cssText || "";
        if (/rubik/i.test(text)) chunks.push(text);
      }
    } catch {
      // cross-origin sheets — ignore
    }
  }
  return chunks.join("\n");
}

/**
 * MAIN PAGE HEADER / PROJECT DETAILS.
 *
 * Rendered inside the repeating <thead> of the document table, so the
 * browser prints it at the top of EVERY physical A4 page. Title is
 * centered; Order Date sits at the right. (Per-page "Page X/Y" numbers
 * cannot be computed inside a repeating <thead>; enable the browser's
 * "Headers and footers" option in the print dialog for page numbers.)
 */
function docHeader(header) {
  return `
    <header class="doc-header">
      <div class="doc-title">
        <div class="h1">OARC/OAMC &amp; Shop Order Details</div>
        <div class="h2">(DUPLICATE)</div>
      </div>
      <div class="meta-right">Order Date: ${esc(today())}</div>
    </header>
    <hr class="rule" />
    <table class="hdr-grid">
      <tr>
        <td><b>Project Name :</b> ${esc(header.project_name)}</td>
        <td><b>Part No :</b> ${esc(header.part_number)}</td>
        <td><b>WBS :</b> ${esc(header.wbs_element)}</td>
      </tr>
      <tr>
        <td><b>Sale order :</b> ${esc(header.sale_order)}</td>
        <td><b>Part Desc :</b> ${esc(header.part_description)}</td>
        <td><b>Tot.No of Oprns :</b> ${esc(header.total_operations)}</td>
      </tr>
      <tr>
        <td><b>Plant :</b> ${esc(header.plant_id)}</td>
        <td><b>Rtg Seq No :</b> 0</td>
        <td><b>Sequence No :</b> 0</td>
      </tr>
      <tr>
        <td><b>Required Qty :</b> ${esc(header.required_quantity)}</td>
        <td><b>Launched Qty :</b> ${esc(header.launched_quantity)}</td>
        <td><b>Prod Order No :</b> ${esc(header.production_order)}</td>
      </tr>
    </table>
    <hr class="rule" />
  `;
}

/** LAST CHANGE / DOCUMENT META — first page only. */
function lastChangeBlock() {
  return `
    <section class="doc-section">
      <table class="plain">
        <tr>
          <td>Last Change By :</td>
          <td>Last Changed Dt :</td>
          <td>Created By :</td>
        </tr>
        <tr>
          <td>Change Number :</td>
          <td>Destination : WIPS</td>
          <td>Storage Bin :</td>
        </tr>
      </table>
    </section>
  `;
}

function documentDetailsBlock(header, documents) {
  const partDigits = s(header.part_number).replace(/\s+/g, "");
  const rows = [];
  if (documents?.partList?.fileName) {
    rows.push({ type: "PL", version: s(documents.partList.version) || "v1", size: "A4" });
  }
  if (documents?.drawing?.fileName) {
    rows.push({ type: "GA", version: s(documents.drawing.version) || "v1", size: "A3" });
  }
  const body = rows.length
    ? rows
        .map(
          (r) => `<tr>
        <td>${esc(partDigits)}</td>
        <td>${esc(r.type)}</td>
        <td>001</td>
        <td>${esc(r.version)}</td>
        <td></td>
        <td></td>
        <td>${esc(r.size)}</td>
      </tr>`,
        )
        .join("")
    : `<tr><td colspan="7">&nbsp;</td></tr>`;

  return `
    <section class="doc-section">
      <div class="section-title">DOCUMENT DETAILS</div>
      <hr class="rule" />
      <table class="data">
        <thead>
          <tr>
            <th>Doc number</th>
            <th>Doc Type</th>
            <th>Doc Part</th>
            <th>Version</th>
            <th>Output Date</th>
            <th>Doc Status</th>
            <th>Sheet Size</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
      <hr class="rule" />
    </section>
  `;
}

function materialsBlock(rawMaterials) {
  const rows = (rawMaterials || [])
    .map(
      (m) => `<tr>
      <td class="pl-item">${esc(opNo4(m["Sl.No"]))}</td>
      <td class="pl-part">${esc(s(m["Child Part No"]).replace(/\s+/g, ""))}</td>
      <td class="pl-desc">${esc(m.Description)}</td>
      <td class="num pl-qty">${esc(qty3(m["Qty Per Set"]))}</td>
      <td class="pl-uom">${esc(m.UoM || "NO")}</td>
      <td class="num pl-total">${esc(qty3(m["Total Qty"]))}</td>
    </tr>`,
    )
    .join("");

  return `
    <section class="doc-section">
      <div class="section-title">PART LIST (PL)</div>
      <hr class="rule" />
      <table class="data pl">
        <colgroup>
          <col class="pl-col-item" />
          <col class="pl-col-part" />
          <col class="pl-col-desc" />
          <col class="pl-col-qty" />
          <col class="pl-col-uom" />
          <col class="pl-col-total" />
        </colgroup>
        <thead>
          <tr>
            <th class="pl-item">Item Sl.No.</th>
            <th class="pl-part">Child Part No</th>
            <th class="pl-desc">Description</th>
            <th class="num pl-qty">Qty Per Set</th>
            <th class="pl-uom">Uom</th>
            <th class="num pl-total">Total Qty</th>
          </tr>
        </thead>
        <tbody>${rows || `<tr><td colspan="6">&nbsp;</td></tr>`}</tbody>
      </table>
      <hr class="rule" />
    </section>
  `;
}

/** SPECIAL NOTE — reserves writable space even when empty. */
function specialNoteBlock() {
  return `
    <section class="doc-section">
      <div class="section-title">SPECIAL NOTE</div>
      <hr class="rule" />
      <div class="special-note-content"></div>
      <hr class="rule" />
    </section>
  `;
}

function operationDetailsHeading() {
  return `
    <div class="section-title op-details-title">OPERATION DETAILS:</div>
  `;
}

function signatureGrid() {
  const blankRow = `<tr><td>&nbsp;</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>`;
  return `
    <table class="sig">
      <thead>
        <tr>
          <th colspan="4">Quantity</th>
          <th rowspan="2" class="sig-ncrf">NCRF NO.</th>
          <th colspan="2">Signature</th>
          <th rowspan="2" class="sig-remarks">First off Remarks</th>
        </tr>
        <tr>
          <th>Offered</th>
          <th>Accp.</th>
          <th>Rej.</th>
          <th>RW.</th>
          <th>Shop</th>
          <th>QA</th>
        </tr>
      </thead>
      <tbody>
        ${blankRow}
        ${blankRow}
        ${blankRow}
      </tbody>
    </table>
  `;
}

/**
 * Bullet characters that appear at the start of instruction lines in the
 * SAP long text (·, •, -, *, or a stray "." followed by spacing). These
 * are normalized to a consistent "• ". Ordinary paragraph lines are
 * left untouched — we never invent bullets.
 */
const BULLET_RE = /^\s*(?:[\u2022\u00B7\u25CF\u25AA\u2023\u2043]|[-*]|\.(?=\s{2,}))\s*/;

function formatLongText(raw) {
  const lines = s(raw)
    .split(/\r?\n/)
    .map((l) => l.trimEnd())
    // Reference-only meta must never print on OARC
    .filter((l) => !/^\s*(Items|Ref|Torque)\s*:/i.test(l));
  // Drop trailing blank lines; keep at most one blank between paragraphs
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  const compact = [];
  for (const line of lines) {
    if (!line.trim()) {
      if (compact.length && compact[compact.length - 1] !== "") compact.push("");
    } else if (BULLET_RE.test(line)) {
      compact.push("\u2022 " + line.replace(BULLET_RE, "").trim());
    } else {
      compact.push(line);
    }
  }
  return compact.map((l) => (l ? esc(l) : "")).join("<br/>");
}

function operationBlock(op, plant) {
  const setup = num(op["Setup Time"], 0);
  const perPc = num(op["Per Pc Time"], 0);
  const allowed = (setup + perPc).toFixed(3);
  const longText = formatLongText(op.LongText || op["Long Text"]);

  return `
    <section class="op-block">
      <div class="op-keep-head">
        <div class="op-title">
          <span class="op-field op-field-no"><span class="op-label">Oprn No:</span> <span class="op-no">${esc(opNo4(op["Oprn No"]))}</span></span>
          <span class="op-field"><span class="op-label">WC:</span> <span class="op-wc">${esc(op["Wc/Plant"])}</span></span>
          <span class="op-field"><span class="op-label">Plant:</span> <span class="op-plant">${esc(plant)}</span></span>
          <span class="op-field op-field-name"><span class="op-label">Oprn Name:</span> <span class="op-name">${esc(op.Operation)}</span></span>
        </div>
        <table class="op-meta">
          <thead>
            <tr>
              <th>SetUp Time Hrs</th>
              <th>Per Pc Time Hrs</th>
              <th>Jmp Qty</th>
              <th>Tot Qty</th>
              <th>Allowed Time Hrs</th>
              <th>Actual Time Hrs</th>
              <th>Confirm No.</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>${esc(hrs(setup))}</td>
              <td>${esc(hrs(perPc))}</td>
              <td>1</td>
              <td>1</td>
              <td>${esc(allowed)}</td>
              <td>&nbsp;</td>
              <td>&nbsp;</td>
            </tr>
          </tbody>
        </table>
        <div class="longtext-label">Long Text / Work Instructions</div>
      </div>
      <div class="longtext">${longText || "&nbsp;"}</div>
      ${signatureGrid()}
    </section>
    <div class="op-sep" aria-hidden="true"></div>
  `;
}

/**
 * Document structure:
 *
 *   <table class="doc">
 *     <thead>  → main header + project details; the browser repeats a
 *                <thead> at the top of every printed page, and reserves
 *                its height so content never prints underneath it.
 *     <tbody>  → first-page-only sections (Last Change, Document
 *                Details, Part List, Special Note, Operation Details
 *                heading) followed by the continuous operation flow.
 *
 * Content paginates naturally — no hardcoded operations per page.
 */
function buildBody(header, operations, rawMaterials, documents) {
  const ops = operations || [];
  return `
    <table class="doc">
      <thead>
        <tr><td>${docHeader(header)}</td></tr>
      </thead>
      <tbody>
        <tr><td>
          ${lastChangeBlock()}
          ${documentDetailsBlock(header, documents)}
          ${materialsBlock(rawMaterials)}
          ${specialNoteBlock()}
          ${operationDetailsHeading()}
          ${ops.map((op) => operationBlock(op, header.plant_id)).join("")}
        </td></tr>
      </tbody>
    </table>
  `;
}

function buildHtml(header, operations, rawMaterials, documents, title) {
  const rubikCss = collectRubikCss();
  const body = buildBody(header, operations, rawMaterials, documents);

  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>${esc(title)}</title>
<style>
${rubikCss}

@page { size: A4 portrait; margin: 8mm 7mm; }

html, body {
  margin: 0;
  padding: 0;
  background: #fff;
  color: #000;
  font-family: "Rubik", system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 8pt;
  line-height: 1.3;
  font-weight: 400;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

b, strong, .section-title, .h1, .h2, th {
  font-weight: 500;
}

.h1 { font-size: 10.5pt; font-weight: 600; }
.h2 { font-size: 9pt; font-weight: 500; }

/* ============ Repeating document table ============ */

table.doc {
  width: 100%;
  border-collapse: collapse;
}
table.doc > thead > tr > td,
table.doc > tbody > tr > td {
  padding: 0;
  vertical-align: top;
}
/* ~one blank line of breathing room between the repeated header and
   whatever content starts on each page. */
table.doc > thead > tr > td {
  padding-bottom: 10px;
}

/* ============ Main page header (repeats every page) ============ */

.doc-header {
  position: relative;
  text-align: center;
  padding: 0 0 2px;
}
.doc-title .h1 { text-align: center; }
.doc-title .h2 { text-align: center; }
.meta-right {
  position: absolute;
  top: 0;
  right: 0;
  text-align: right;
  font-size: 7.5pt;
}

.rule {
  border: 0;
  border-top: 1px solid #000;
  margin: 2px 0 3px;
}

.hdr-grid {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 7.5pt;
  text-align: left;
}
.hdr-grid td {
  vertical-align: top;
  padding: 1px 4px 1px 0;
  width: 33.33%;
}

/* ============ First-page sections ============ */

/* Vertical rhythm between top-level document sections */
.doc-section {
  margin: 0 0 10px;
}

.section-title {
  font-size: 8.5pt;
  font-weight: 500;
  margin: 0 0 2px;
}

/* Blank writable area inside SPECIAL NOTE (~2 text lines) */
.special-note-content {
  min-height: 2.8em;
}

/* Heading before the operation flow */
.op-details-title {
  margin: 0 0 4mm;
}

table.plain {
  width: 100%;
  border-collapse: collapse;
  font-size: 7.5pt;
}
table.plain td {
  padding: 1px 6px 1px 0;
  width: 33.33%;
}

table.data {
  width: 100%;
  border-collapse: collapse;
  font-size: 7.5pt;
  margin: 0 0 2px;
}
table.data th {
  text-align: left;
  font-weight: 500;
  padding: 1px 3px;
  border-bottom: 1px solid #000;
  vertical-align: bottom;
}
table.data td {
  padding: 1px 3px;
  vertical-align: top;
  border-bottom: none;
}
table.data .num,
table.data th.num {
  text-align: right;
  white-space: nowrap;
}

/* PART LIST — fixed columns so Qty Per Set / Uom / Total Qty stay aligned */
table.data.pl {
  table-layout: fixed;
}
table.data.pl col.pl-col-item { width: 9%; }
table.data.pl col.pl-col-part { width: 15%; }
table.data.pl col.pl-col-desc { width: 40%; }
table.data.pl col.pl-col-qty { width: 12%; }
table.data.pl col.pl-col-uom { width: 8%; }
table.data.pl col.pl-col-total { width: 16%; }
table.data.pl th,
table.data.pl td {
  overflow: hidden;
  text-overflow: ellipsis;
}
table.data.pl .pl-qty {
  padding-right: 10px;
  padding-left: 6px;
}
table.data.pl .pl-uom {
  text-align: left;
  padding-left: 6px;
  padding-right: 6px;
}
table.data.pl .pl-total {
  padding-left: 8px;
  padding-right: 2px;
}
table.data.pl .pl-desc {
  overflow-wrap: anywhere;
  white-space: normal;
}

/* ============ Operation section ============ */

.op-block {
  margin: 0 0 6mm;
  /* Keep small/medium operations together; browsers still split a block
     that is taller than one page (break-inside:avoid is best-effort),
     so oversized operations continue naturally without a blank page. */
  break-inside: avoid;
  page-break-inside: avoid;
}

/* Separator between operations — light and optional; spacing does most of the work. */
.op-sep {
  border-top: 0.5px solid #ccc;
  margin: 0 0 5mm;
}
.op-sep:last-child { border-top: none; margin: 0; }

/* Orphan protection: title + metadata + instructions label move as one
   unit, and never allow a break right after them. */
.op-keep-head {
  break-inside: avoid;
  page-break-inside: avoid;
  break-after: avoid;
  page-break-after: avoid;
}

/* --- Title bar: labeled Oprn No / WC / Plant / Oprn Name --- */
.op-title {
  display: flex;
  align-items: baseline;
  gap: 14px;
  border-top: none;
  border-bottom: 0.5px solid #888;
  padding: 3px 2px 4px;
  margin-bottom: 2px;
}
.op-field { white-space: nowrap; }
.op-field-name {
  flex: 1;
  white-space: normal;
}
.op-label {
  font-size: 7.5pt;
  font-weight: 500;
  color: #333;
}
.op-no {
  font-size: 8.5pt;
  font-weight: 500;
  letter-spacing: 0.02em;
}
.op-wc {
  font-size: 8.5pt;
  font-weight: 500;
}
.op-plant {
  font-size: 8.5pt;
  font-weight: 400;
}
.op-name {
  font-size: 8.5pt;
  font-weight: 500;
}

/* --- Secondary metadata strip (no rules — padding only) --- */
table.op-meta {
  width: 100%;
  border-collapse: collapse;
  font-size: 7.5pt;
  margin: 0 0 4px;
}
table.op-meta th {
  text-align: center;
  font-weight: 500;
  color: #222;
  padding: 3px 4px 1px;
  border: none;
  white-space: nowrap;
}
table.op-meta td {
  text-align: center;
  padding: 1px 4px 4px;
  border: none;
}

/* --- Work instructions (Long Text): left accent + background only --- */
.longtext-label {
  font-size: 8pt;
  font-weight: 500;
  margin: 3px 0 2px;
}
.longtext {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: "Roboto Mono", Consolas, "Cascadia Mono", "Courier New", ui-monospace, monospace;
  font-size: 8pt;
  font-weight: 400;
  line-height: 1.35;
  background: #f6f6f6;
  border: none;
  border-left: 1.5pt solid #999;
  padding: 4px 8px;
  margin: 0 0 5px;
}

/* --- Quantity / NCRF / Signature grid (writable — keep clearer borders) --- */
table.sig {
  width: 100%;
  border-collapse: collapse;
  font-size: 7.5pt;
  margin: 0;
  break-inside: avoid;
  page-break-inside: avoid;
  border: 0.75pt solid #555;
}
table.sig th, table.sig td {
  border: 0.5px solid #888;
  padding: 2px 4px;
  text-align: left;
  font-weight: 400;
}
table.sig th {
  font-weight: 500;
  text-align: center;
  vertical-align: middle;
}
table.sig .sig-ncrf { width: 12%; }
table.sig .sig-remarks { width: 24%; }
/* Room for handwritten entries after printing */
table.sig tbody td { height: 20px; }
</style>
</head>
<body>
${body}
</body>
</html>`;
}

export function printOarcPdf(header, operations, rawMaterials, documents) {
  const partNo = s(header.part_number).replace(/\s+/g, "");
  const title = `OARC_${s(header.part_description) || partNo || "Order"}`;
  const html = buildHtml(header, operations, rawMaterials, documents, title);

  const iframe = document.createElement("iframe");
  iframe.style.cssText =
    "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden;";
  iframe.setAttribute("aria-hidden", "true");
  document.body.appendChild(iframe);

  const cleanup = () => {
    setTimeout(() => {
      if (iframe.parentNode) iframe.parentNode.removeChild(iframe);
    }, 1000);
  };

  const win = iframe.contentWindow;
  const doc = win.document;
  doc.open();
  doc.write(html);
  doc.close();

  const doPrint = () => {
    try {
      doc.title = title;
      win.focus();
      win.print();
    } finally {
      win.onafterprint = cleanup;
      setTimeout(cleanup, 60_000);
    }
  };

  if (doc.readyState === "complete") {
    // Give the browser a tick to apply @font-face from collected Rubik CSS
    setTimeout(doPrint, 50);
  } else {
    iframe.onload = () => setTimeout(doPrint, 50);
  }
}
