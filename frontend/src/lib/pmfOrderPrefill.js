/**
 * Map route-card analysis payload → CreateOrderModal-style rows
 * (Oprn No, LongText, Raw Materials). Reference only — lives in this project.
 */

let _rowSeq = 0;
function rowId(prefix) {
  _rowSeq += 1;
  return `${prefix}-${Date.now()}-${_rowSeq}`;
}

function asList(v) {
  return Array.isArray(v) ? v : [];
}

function str(v, fallback = "") {
  if (v == null) return fallback;
  return String(v).trim();
}

function num(v, fallback = 0) {
  if (v == null || v === "") return fallback;
  const n = typeof v === "number" ? v : Number(String(v).replace(/,/g, ""));
  return Number.isFinite(n) ? n : fallback;
}

function opNo(raw, index) {
  const n = num(raw, 0);
  if (n > 0) {
    if (n % 10 === 0) return n;
    return n < 10 ? n * 10 : n;
  }
  return (index + 1) * 10;
}

function instructionForOp(op, notes) {
  let text = str(op.instructionText || op.reason);
  if (text) return text;
  const want = num(op.opNo, null);
  for (const note of asList(notes)) {
    if (want != null && num(note.stepNo, null) === want) {
      return str(note.text);
    }
  }
  return "";
}

/** Strip legacy Items/Ref/Torque lines that used to be appended into LongText. */
export function stripMetaFromLongText(text) {
  return String(text || "")
    .split(/\r?\n/)
    .filter((line) => !/^\s*(Items|Ref|Torque)\s*:/i.test(line))
    .join("\n")
    .trim();
}

/** Parse "#42×1, #22×1" style labels into { itemNo, qty } when itemsUsed is empty. */
export function parseItemsLabel(label) {
  const out = [];
  const re = /#\s*(\d+)\s*[×xX*]?\s*(\d+(?:\.\d+)?)?/g;
  let m;
  const src = String(label || "");
  while ((m = re.exec(src))) {
    out.push({
      itemNo: Number(m[1]),
      qty: m[2] != null && m[2] !== "" ? Number(m[2]) : null,
    });
  }
  return out;
}

function normalizeItemsUsed(op) {
  const used = asList(op?.itemsUsed).filter((i) => i?.itemNo != null);
  if (used.length) {
    return used.map((i) => ({
      itemNo: i.itemNo,
      qty: i.qty ?? null,
      description: i.description || "",
      partNumber: i.partNumber || i.part_number || "",
    }));
  }
  return parseItemsLabel(op?.items);
}

function mergeItemsUsed(a, b) {
  const map = new Map();
  for (const it of [...asList(a), ...asList(b)]) {
    if (it?.itemNo == null) continue;
    const key = String(it.itemNo);
    const prev = map.get(key);
    if (!prev) {
      map.set(key, { ...it });
      continue;
    }
    map.set(key, {
      ...prev,
      ...it,
      qty: prev.qty != null || it.qty != null ? num(prev.qty, 0) + num(it.qty, 0) : null,
      description: prev.description || it.description || "",
      partNumber: prev.partNumber || it.partNumber || "",
    });
  }
  return [...map.values()];
}

export function mapPayloadToOrderPrefill(payload, { requiredQty = 1 } = {}) {
  const info = payload?.drawingInfo || {};
  const notes = asList(payload?.notes);
  const opsSrc = asList(payload?.routeOperations?.length ? payload.routeOperations : payload?.suggestedOperations);
  const plItems = asList(payload?.partsList?.items);
  const bom = asList(payload?.bomItems);
  const materialSrc = plItems.length ? plItems : bom;
  const qty = num(requiredQty, 1) || 1;

  const operations = opsSrc
    .map((op, i) => {
      const desc = str(op.operation);
      if (!desc) return null;
      const wc = str(op.workCentre || op.workCenter);
      const longText = stripMetaFromLongText(instructionForOp(op, notes));
      const itemsUsed = normalizeItemsUsed(op);

      return {
        _rowId: rowId("op"),
        "Oprn No": opNo(op.opNo, i),
        "Wc/Plant": wc,
        Operation: desc,
        "Setup Time": num(op.setup, 0),
        "Per Pc Time": num(op.time, 0),
        LongText: longText,
        _itemsUsed: itemsUsed,
        _itemsLabel: str(op.items) || (itemsUsed.length
          ? itemsUsed
              .map((it) => `#${it.itemNo}${it.qty != null ? `×${it.qty}` : ""}`)
              .join(", ")
          : ""),
        _reference: str(op.reference),
        _torqueSpec: str(op.torqueSpec),
        generates_output_serial: false,
        requires_input_material: false,
        manual_operation: true,
      };
    })
    .filter(Boolean);

  const rawMaterials = materialSrc
    .map((it, i) => {
      const partNo = str(it.partNumber || it.part_number);
      const desc = str(it.description || it.designation);
      if (!partNo && !desc) return null;
      const qtyPerSet = num(it.qty ?? it.quantity, 1) || 1;
      return {
        _rowId: rowId("rm"),
        "Sl.No": (i + 1) * 10,
        "Child Part No": partNo,
        Description: desc,
        "Qty Per Set": qtyPerSet,
        UoM: str(it.unit || "NO") || "NO",
        "Total Qty": qtyPerSet * qty,
      };
    })
    .filter(Boolean);

  const header = {
    production_order: "",
    sale_order: "",
    project_name: str(info.partName) || "Route Card Import",
    priority: "normal",
    wbs_element: "",
    part_number: str(info.partNumber || info.drawingNumber),
    part_description: str(info.partName || info.title),
    total_operations: operations.length || 1,
    required_quantity: qty,
    launched_quantity: qty,
    plant_id: "",
  };

  return { header, operations, rawMaterials };
}

/** Build downloadable OARC JSON from editable prefill state (CreateOrderModal shape). */
export function buildOarcJson(header, operations, rawMaterials) {
  const ops = asList(operations).map(({ _rowId, ...rest }) => ({
    "Oprn No": rest["Oprn No"],
    "Wc/Plant": rest["Wc/Plant"] || "",
    "Work Center": rest["Wc/Plant"] || "",
    work_center_code: rest["Wc/Plant"] || "",
    Operation: rest.Operation || "",
    "Setup Time": num(rest["Setup Time"], 0),
    "Per Pc Time": num(rest["Per Pc Time"], 0),
    LongText: stripMetaFromLongText(rest.LongText || ""),
    "Plant Number": "",
    "Jmp Qty": 0,
    "Tot Qty": 0,
    "Allowed Time": 0,
    "Confirm No": "",
    generates_output_serial: Boolean(rest.generates_output_serial),
    requires_input_material: Boolean(rest.requires_input_material),
    manual_operation: rest.manual_operation !== false,
  }));

  const mats = asList(rawMaterials).map(({ _rowId, ...rest }) => ({
    "Sl.No": rest["Sl.No"],
    "Child Part No": rest["Child Part No"] || "",
    Description: rest.Description || "",
    "Qty Per Set": num(rest["Qty Per Set"], 0),
    UoM: rest.UoM || "NO",
    "Total Qty": num(rest["Total Qty"], 0),
  }));

  return {
    source: "route-card-app",
    "Project Name": header.project_name || "",
    "Sale Order": header.sale_order || "",
    "Part No": header.part_number || "",
    "Part Desc": header.part_description || "",
    "Required Qty": num(header.required_quantity, 1),
    Plant: header.plant_id || "",
    WBS: header.wbs_element || "",
    "Rtg Seq No": "0",
    "Sequence No": "0",
    "Launched Qty": num(header.launched_quantity, 0),
    "Prod Order No": header.production_order || "",
    Priority: header.priority || "normal",
    "Total Operations": ops.length || 1,
    Operations: ops,
    "Raw Materials": mats,
    "Document Verification": {},
  };
}

export function emptyOperation(ops = []) {
  const nums = asList(ops).map((o) => num(o["Oprn No"], 0));
  const next = nums.length ? (Math.floor(Math.max(...nums) / 10) + 1) * 10 : 10;
  return {
    _rowId: rowId("op"),
    "Oprn No": next,
    "Wc/Plant": "",
    Operation: "",
    "Setup Time": 0,
    "Per Pc Time": 0,
    LongText: "",
    _itemsUsed: [],
    _itemsLabel: "",
    _reference: "",
    _torqueSpec: "",
    generates_output_serial: false,
    requires_input_material: false,
    manual_operation: true,
  };
}

export function emptyRawMaterial(mats = []) {
  const nums = asList(mats).map((m) => num(m["Sl.No"], 0));
  const next = nums.length ? (Math.floor(Math.max(...nums) / 10) + 1) * 10 : 10;
  return {
    _rowId: rowId("rm"),
    "Sl.No": next,
    "Child Part No": "",
    Description: "",
    "Qty Per Set": 1,
    UoM: "NO",
    "Total Qty": 1,
  };
}

/** Map an operation-template step → OARC Create-Order row. */
export function templateStepToOarcRow(step) {
  return {
    _rowId: rowId("op"),
    "Oprn No": 0,
    "Wc/Plant": str(step?.workCentre),
    Operation: str(step?.operation),
    "Setup Time": num(step?.setup, 0),
    "Per Pc Time": num(step?.time, 0),
    LongText: stripMetaFromLongText(str(step?.instructionText)),
    _itemsUsed: [],
    _itemsLabel: "",
    _reference: "",
    _torqueSpec: "",
    generates_output_serial: Boolean(step?.generates_output_serial),
    requires_input_material: Boolean(step?.requires_input_material),
    manual_operation: step?.manual_operation !== false,
  };
}

/** Map an operation-template step → route editor op row. */
export function templateStepToRouteOp(step) {
  return {
    id: `op-tpl-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    opNo: 0,
    operation: str(step?.operation),
    workCentre: str(step?.workCentre),
    machine: str(step?.machine) || "Assembly station",
    tool: str(step?.tool),
    items: "",
    itemsUsed: [],
    torqueSpec: "",
    reference: "",
    setup: str(step?.setup) || "1",
    time: str(step?.time),
    inspection: str(step?.inspection),
    instructionText: str(step?.instructionText),
    status: "Planned",
  };
}

/**
 * Insert template steps into an existing ops list.
 * placement: pre | post | any (any → end)
 */
export function insertTemplateSteps(existing, steps, placement, mapStep) {
  const mapped = asList(steps).map(mapStep).filter((r) => str(r.Operation || r.operation));
  if (!mapped.length) return asList(existing);
  const base = asList(existing);
  const place = String(placement || "any").toLowerCase();
  if (place === "pre") return [...mapped, ...base];
  return [...base, ...mapped];
}

export function renumberOarcOps(rows) {
  return asList(rows).map((row, i) => ({
    ...row,
    "Oprn No": (i + 1) * 10,
  }));
}

function wcKey(op) {
  return str(op?.["Wc/Plant"] || op?.workCentre || op?.workCenter).toLowerCase();
}

/**
 * Merge consecutive OARC ops that share the same non-empty work centre.
 * Returns { rows, mergedGroups, beforeCount, afterCount }.
 */
export function squashConsecutiveSameWc(ops) {
  const src = asList(ops);
  if (src.length < 2) {
    return {
      rows: renumberOarcOps(src.map((r) => ({ ...r }))),
      mergedGroups: 0,
      beforeCount: src.length,
      afterCount: src.length,
    };
  }

  const out = [];
  let mergedGroups = 0;
  let groupOpen = false;

  for (const op of src) {
    const key = wcKey(op);
    const prev = out[out.length - 1];
    const prevKey = prev ? wcKey(prev) : "";

    if (prev && key && key === prevKey) {
      const names = [str(prev.Operation), str(op.Operation)].filter(Boolean);
      prev.Operation = names.join("; ");
      const texts = [str(prev.LongText), str(op.LongText)].filter(Boolean);
      prev.LongText = texts.join("\n\n");
      prev["Setup Time"] = num(prev["Setup Time"], 0) + num(op["Setup Time"], 0);
      prev["Per Pc Time"] = num(prev["Per Pc Time"], 0) + num(op["Per Pc Time"], 0);
      prev._itemsUsed = mergeItemsUsed(prev._itemsUsed, op._itemsUsed);
      prev._itemsLabel = [str(prev._itemsLabel), str(op._itemsLabel)].filter(Boolean).join(", ");
      prev._reference = [str(prev._reference), str(op._reference)].filter(Boolean).join("; ");
      prev._torqueSpec = [str(prev._torqueSpec), str(op._torqueSpec)].filter(Boolean).join("; ");
      prev.generates_output_serial =
        Boolean(prev.generates_output_serial) || Boolean(op.generates_output_serial);
      prev.requires_input_material =
        Boolean(prev.requires_input_material) || Boolean(op.requires_input_material);
      prev.manual_operation =
        prev.manual_operation !== false || op.manual_operation !== false;
      if (!groupOpen) {
        mergedGroups += 1;
        groupOpen = true;
      }
    } else {
      groupOpen = false;
      out.push({ ...op });
    }
  }

  const rows = renumberOarcOps(out);
  return {
    rows,
    mergedGroups,
    beforeCount: src.length,
    afterCount: rows.length,
  };
}

export function renumberRouteOps(rows) {
  return asList(rows).map((row, i) => ({
    ...row,
    opNo: (i + 1) * 10,
  }));
}
