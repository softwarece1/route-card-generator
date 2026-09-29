import React, { useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Checkbox } from "primereact/checkbox";
import { Column } from "primereact/column";
import { DataTable } from "primereact/datatable";
import { Dialog } from "primereact/dialog";
import { InputNumber } from "primereact/inputnumber";
import { InputText } from "primereact/inputtext";
import { InputTextarea } from "primereact/inputtextarea";
import { Message } from "primereact/message";
import { TabPanel, TabView } from "primereact/tabview";
import { Tooltip } from "primereact/tooltip";
import { confirmDialog } from "primereact/confirmdialog";
import { toast } from "@/lib/toast";
import {
  buildOarcJson,
  emptyOperation,
  emptyRawMaterial,
  insertTemplateSteps,
  mapPayloadToOrderPrefill,
  parseItemsLabel,
  renumberOarcOps,
  squashConsecutiveSameWc,
  stripMetaFromLongText,
  templateStepToOarcRow,
} from "@/lib/pmfOrderPrefill";
import { printOarcPdf } from "@/lib/oarcPrint";
import { downloadJson } from "@/services/routeCardApi";
import OpTemplatePickerDialog from "@/components/OpTemplatePickerDialog";
import "./oarc-preview-dialog.scss";

/**
 * View OARC preview — CreateOrderModal-shaped dialog (this project only).
 * Prefills from extract + uploaded drawing/PL; leaves unknown fields empty.
 */
export default function OarcPreviewDialog({
  visible,
  onHide,
  payload,
  docs = {},
}) {
  const [header, setHeader] = useState(null);
  const [operations, setOperations] = useState([]);
  const [rawMaterials, setRawMaterials] = useState([]);
  const [tab, setTab] = useState(0);
  const [instr, setInstr] = useState({
    visible: false,
    rowId: null,
    title: "",
    draft: "",
    itemsUsed: [],
    reference: "",
    torqueSpec: "",
  });
  const emptyInstr = () => ({
    visible: false,
    rowId: null,
    title: "",
    draft: "",
    itemsUsed: [],
    reference: "",
    torqueSpec: "",
  });
  const [drawingMeta, setDrawingMeta] = useState({
    name: "",
    description: "",
    version: "v1",
    fileName: "",
  });
  const [plMeta, setPlMeta] = useState({
    name: "",
    description: "",
    version: "v1",
    fileName: "",
  });
  const [tplPickerOpen, setTplPickerOpen] = useState(false);

  const itemLookup = useMemo(() => {
    const map = {};
    for (const it of payload?.partsList?.items || []) {
      if (it?.itemNo == null) continue;
      map[String(it.itemNo)] = it;
    }
    for (const it of payload?.bomItems || []) {
      if (it?.itemNo == null) continue;
      const key = String(it.itemNo);
      map[key] = { ...map[key], ...it };
    }
    return map;
  }, [payload]);

  const remapKey = useMemo(() => {
    if (!payload) return "";
    const ops = payload.routeOperations || payload.suggestedOperations || [];
    const mats = payload.partsList?.items || payload.bomItems || [];
    return [
      payload.id,
      ops.length,
      ops.map((o) => `${o.id}:${o.opNo}:${o.operation}`).join("|"),
      mats.length,
      mats.map((m) => `${m.itemNo}:${m.partNumber}:${m.qty}`).join("|"),
      payload.drawingInfo?.partNumber,
      docs.drawing?.name,
      docs.partslist?.name,
    ].join("::");
  }, [payload, docs.drawing?.name, docs.partslist?.name]);

  useEffect(() => {
    if (!visible || !payload) return;
    const mapped = mapPayloadToOrderPrefill(payload, { requiredQty: 1 });
    // Leave unavailable ERP fields empty
    setHeader({
      ...mapped.header,
      production_order: "",
      sale_order: "",
      wbs_element: "",
      plant_id: "",
      priority: mapped.header.priority || "normal",
      total_operations: mapped.operations.length || 0,
    });
    setOperations(mapped.operations);
    setRawMaterials(mapped.rawMaterials);

    const dwg = docs.drawing;
    const pl = docs.partslist;
    const partNo = mapped.header.part_number || "";
    setDrawingMeta({
      name: dwg?.name ? dwg.name.replace(/\.[^.]+$/, "") : partNo ? `${partNo} Drawing` : "",
      description: mapped.header.part_description || "",
      version: "v1",
      fileName: dwg?.name || "",
    });
    setPlMeta({
      name: pl?.name ? pl.name.replace(/\.[^.]+$/, "") : partNo ? `${partNo} Parts List` : "",
      description: "",
      version: "v1",
      fileName: pl?.name || "",
    });
    setTab(0);
  }, [visible, remapKey, payload, docs.drawing, docs.partslist]);

  const setH = (key, value) => setHeader((h) => (h ? { ...h, [key]: value } : h));

  /** Keep Oprn No ascending 10, 20, 30… after reorder / delete */
  const renumberOps = (rows) =>
    rows.map((row, i) => ({
      ...row,
      "Oprn No": (i + 1) * 10,
    }));

  const updateOp = (rowId, field, value) => {
    setOperations((rows) =>
      rows.map((r) => (r._rowId === rowId ? { ...r, [field]: value } : r)),
    );
  };

  const onOpsReorder = (e) => {
    const next = renumberOps(e.value || []);
    setOperations(next);
    setH("total_operations", next.length);
  };

  const deleteOp = (rowId) => {
    setOperations((rows) => {
      const next = renumberOps(rows.filter((r) => r._rowId !== rowId));
      setH("total_operations", next.length);
      return next;
    });
  };

  const addOp = () => {
    setOperations((rows) => {
      const next = renumberOps([...rows, emptyOperation(rows)]);
      setH("total_operations", next.length);
      return next;
    });
  };

  const addFromTemplate = (tpl) => {
    setOperations((rows) => {
      const merged = insertTemplateSteps(
        rows,
        tpl?.steps || [],
        tpl?.placement,
        templateStepToOarcRow,
      );
      const next = renumberOarcOps(merged);
      setH("total_operations", next.length);
      return next;
    });
    toast.success(
      `Inserted ${(tpl?.steps || []).length} operation(s) from "${tpl?.name || "template"}"`,
    );
  };

  const mergePreview = useMemo(() => squashConsecutiveSameWc(operations), [operations]);
  const canMergeSameWc =
    mergePreview.beforeCount > mergePreview.afterCount && mergePreview.mergedGroups > 0;

  const mergeSameWcOps = () => {
    const preview = squashConsecutiveSameWc(operations);
    if (preview.beforeCount <= preview.afterCount) {
      toast.info("No consecutive operations share the same work centre.");
      return;
    }
    const removed = preview.beforeCount - preview.afterCount;
    confirmDialog({
      header: "Merge same WC",
      message: `Combine ${preview.mergedGroups} group(s) of consecutive same-WC ops? ${preview.beforeCount} → ${preview.afterCount} (merge ${removed}).`,
      icon: "pi pi-objects-column",
      className: "p-confirm-dialog-sm",
      acceptLabel: "Merge",
      rejectLabel: "Cancel",
      acceptClassName: "p-button-sm",
      rejectClassName: "p-button-sm p-button-outlined",
      accept: () => {
        setOperations(preview.rows);
        setH("total_operations", preview.rows.length);
        toast.success(
          `Merged to ${preview.afterCount} operation(s) (${preview.mergedGroups} WC group(s)).`,
        );
      },
    });
  };

  const updateMat = (rowId, field, value) => {
    setRawMaterials((rows) =>
      rows.map((r) => {
        if (r._rowId !== rowId) return r;
        const next = { ...r, [field]: value };
        if (field === "Qty Per Set") {
          next["Total Qty"] = Number(value || 0) * Number(header?.required_quantity || 1);
        }
        return next;
      }),
    );
  };

  const onRequiredQty = (value) => {
    const q = Number(value || 1) || 1;
    setHeader((h) =>
      h
        ? {
            ...h,
            required_quantity: q,
            launched_quantity: q,
            total_operations: operations.length,
          }
        : h,
    );
    setRawMaterials((rows) =>
      rows.map((r) => ({
        ...r,
        "Total Qty": Number(r["Qty Per Set"] || 0) * q,
      })),
    );
  };

  const openInstruction = (row) => {
    const used =
      Array.isArray(row._itemsUsed) && row._itemsUsed.length
        ? row._itemsUsed
        : parseItemsLabel(row._itemsLabel);
    setInstr({
      visible: true,
      rowId: row._rowId,
      title: `OP ${row["Oprn No"]} — ${row.Operation || "Operation"}`,
      draft: stripMetaFromLongText(row.LongText || ""),
      itemsUsed: used,
      reference: row._reference || "",
      torqueSpec: row._torqueSpec || "",
    });
  };

  const saveInstruction = () => {
    if (instr.rowId) updateOp(instr.rowId, "LongText", stripMetaFromLongText(instr.draft));
    setInstr(emptyInstr());
  };

  const handlePrint = () => {
    if (!header) return;
    try {
      printOarcPdf(header, operations, rawMaterials, {
        drawing: drawingMeta,
        partList: plMeta,
      });
    } catch (error) {
      toast.error(error.message || "Could not open print preview");
    }
  };

  const handleExport = () => {
    if (!header) return;
    const oarc = buildOarcJson(header, operations, rawMaterials);
    oarc._documents = {
      engineering_drawing: { ...drawingMeta },
      part_list: { ...plMeta },
    };
    const pn = (header.part_number || "order").replace(/\s+/g, "");
    downloadJson(`oarc-preview-${pn || "export"}.json`, oarc);
    toast.success("OARC preview JSON downloaded.");
  };

  const footer = (
    <div className="oarc-preview-dialog__footer">
      <Button type="button" label="Close" outlined size="small" onClick={onHide} />
      <Button type="button" label="Export to SAP" icon="pi pi-download" outlined size="small" onClick={handleExport} />
      <Button type="button" label="Print" icon="pi pi-print" size="small" onClick={handlePrint} />
    </div>
  );

  return (
    <>
      <Dialog
        header="View OARC preview"
        visible={visible}
        onHide={onHide}
        className="oarc-preview-dialog"
        style={{ width: "min(96vw, 88rem)" }}
        breakpoints={{ "1400px": "94vw", "960px": "98vw" }}
        maximizable
        modal
        blockScroll
        footer={footer}
      >
        {!header ? (
          <Message severity="warn" className="w-full" text="Analyze a session first to open the OARC preview." />
        ) : (
          <div className="oarc-preview-dialog__body" id="oarc-preview-print-root">
            <Message
              severity="info"
              className="w-full mb-3"
              text="Fields filled from GA / NOTES / Parts List extract. Production Order, SO, WBS, and Plant stay empty until you enter them."
            />

            <div className="om-order-form om-order-form--two-col">
              <div className="om-section">
                <div className="om-section-header">
                  <i className="pi pi-briefcase" />
                  <span>Project &amp; Order Context</span>
                </div>
                <div className="grid formgrid om-grid">
                  <div className="field col-12">
                    <label>Production Order *</label>
                    <InputText
                      className="om-input"
                      value={header.production_order}
                      onChange={(e) => setH("production_order", e.target.value)}
                      placeholder="Enter production order"
                    />
                  </div>
                  <div className="field col-12">
                    <label>WBS Element *</label>
                    <InputText
                      className="om-input"
                      value={header.wbs_element}
                      onChange={(e) => setH("wbs_element", e.target.value)}
                      placeholder="WBS element"
                    />
                  </div>
                  <div className="field col-12">
                    <label>Sales Order *</label>
                    <InputText
                      className="om-input"
                      value={header.sale_order}
                      onChange={(e) => setH("sale_order", e.target.value)}
                      placeholder="Enter sales order"
                    />
                  </div>
                  <div className="field col-12">
                    <label>Project Name *</label>
                    <InputText
                      className="om-input"
                      value={header.project_name}
                      onChange={(e) => setH("project_name", e.target.value)}
                      placeholder="Project name"
                    />
                  </div>
                  <div className="field col-12">
                    <label>Priority *</label>
                    <InputText
                      className="om-input"
                      value={header.priority}
                      onChange={(e) => setH("priority", e.target.value)}
                      placeholder="Priority"
                    />
                  </div>
                </div>
              </div>

              <div className="om-section">
                <div className="om-section-header">
                  <i className="pi pi-box" />
                  <span>Part &amp; Work Scope</span>
                </div>
                <div className="grid formgrid om-grid">
                  <div className="field col-12">
                    <label>Part Number *</label>
                    <InputText
                      className="om-input"
                      value={header.part_number}
                      onChange={(e) => setH("part_number", e.target.value)}
                      placeholder="Part number"
                    />
                  </div>
                  <div className="field col-12">
                    <label>Part Description *</label>
                    <InputText
                      className="om-input"
                      value={header.part_description}
                      onChange={(e) => setH("part_description", e.target.value)}
                      placeholder="Part description"
                    />
                  </div>
                  <div className="field col-12 md:col-6">
                    <label>Required Qty *</label>
                    <InputNumber
                      className="w-full"
                      value={header.required_quantity}
                      onValueChange={(e) => onRequiredQty(e.value)}
                      min={1}
                    />
                  </div>
                  <div className="field col-12 md:col-6">
                    <label>Launched Qty *</label>
                    <InputNumber
                      className="w-full"
                      value={header.launched_quantity}
                      onValueChange={(e) => setH("launched_quantity", e.value ?? 0)}
                      min={0}
                    />
                  </div>
                  <div className="field col-12 md:col-6">
                    <label>Plant ID *</label>
                    <InputText
                      className="om-input"
                      value={header.plant_id === "" || header.plant_id == null ? "" : String(header.plant_id)}
                      onChange={(e) => setH("plant_id", e.target.value)}
                      placeholder="Plant ID"
                    />
                  </div>
                  <div className="field col-12 md:col-6">
                    <label>No. of Operations *</label>
                    <InputNumber
                      className="w-full"
                      value={operations.length || header.total_operations || 0}
                      onValueChange={(e) => setH("total_operations", e.value ?? 0)}
                      min={0}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="om-create-order-ops-tabs mb-3">
              <TabView
                activeIndex={tab}
                onTabChange={(e) => setTab(e.index)}
                className="om-zepto-tabs"
                headerTemplate={(options) => {
                  const tabs = [
                    { label: "Operations", icon: "pi pi-sitemap", count: operations.length },
                    { label: "Raw Materials", icon: "pi pi-box", count: rawMaterials.length },
                    {
                      label: "Documents",
                      icon: "pi pi-folder",
                      count: (drawingMeta.fileName ? 1 : 0) + (plMeta.fileName ? 1 : 0),
                    },
                  ];
                  const meta = tabs[options.index] || tabs[0];
                  return (
                    <button
                      type="button"
                      className={options.className}
                      onClick={options.onClick}
                      onKeyDown={options.onKeyDown}
                      aria-controls={options.ariaControls}
                      aria-selected={options.selected}
                      tabIndex={options.tabindex}
                    >
                      <span className="om-zepto-tab-label">
                        <i className={meta.icon} aria-hidden />
                        <span>{meta.label}</span>
                        <span className="om-zepto-tab-count">{meta.count}</span>
                      </span>
                    </button>
                  );
                }}
              >
                <TabPanel header="Operations">
                  <div className="om-create-order-section">
                    <div className="om-create-order-section__toolbar">
                      <span className="om-create-order-section__hint">
                        {operations.length
                          ? "Drag rows to reorder. Operation numbers stay ascending (10, 20, 30…)."
                          : "No operations found. Click 'Add Operation' to add new operations:"}
                      </span>
                      <div className="flex gap-2 flex-wrap">
                        <Button
                          type="button"
                          label="Merge same WC"
                          icon="pi pi-objects-column"
                          size="small"
                          outlined
                          disabled={!canMergeSameWc}
                          tooltip={
                            canMergeSameWc
                              ? `Merge consecutive ops with the same work centre (${mergePreview.beforeCount} → ${mergePreview.afterCount})`
                              : "No consecutive operations share the same work centre"
                          }
                          tooltipOptions={{ position: "top" }}
                          onClick={mergeSameWcOps}
                        />
                        <Button
                          type="button"
                          label="Add from template"
                          icon="pi pi-list"
                          size="small"
                          outlined
                          onClick={() => setTplPickerOpen(true)}
                        />
                        <Button
                          type="button"
                          label="Add Operation"
                          size="small"
                          onClick={addOp}
                        />
                      </div>
                    </div>
                    <DataTable
                      value={operations}
                      dataKey="_rowId"
                      scrollable
                      scrollHeight="360px"
                      tableStyle={{ minWidth: "78rem" }}
                      className="om-create-order-table"
                      reorderableRows
                      onRowReorder={onOpsReorder}
                      emptyMessage={
                        <div className="om-create-order-empty">
                          <p>No operations added yet.</p>
                          <p className="om-create-order-empty__sub">
                            Click &quot;Add Operation&quot; to start adding operations.
                          </p>
                        </div>
                      }
                    >
                      <Column rowReorder style={{ width: "3rem", minWidth: "3rem" }} />
                      <Column
                        header="Operation No"
                        style={{ minWidth: "7.5rem", width: "7.5rem" }}
                        body={(row) => (
                          <span className="om-oprn-no">{row["Oprn No"]}</span>
                        )}
                      />
                      <Column
                        header="Workcenter"
                        style={{ minWidth: "14rem" }}
                        body={(row) => (
                          <InputText
                            value={row["Wc/Plant"]}
                            className="w-full"
                            placeholder="Select workcenter"
                            onChange={(e) => updateOp(row._rowId, "Wc/Plant", e.target.value)}
                          />
                        )}
                      />
                      <Column
                        header="Operation"
                        style={{ minWidth: "28rem" }}
                        body={(row) => {
                          const hasInstruction = Boolean(String(row.LongText || "").trim());
                          return (
                            <div className="om-op-desc-field">
                              <InputText
                                value={row.Operation}
                                placeholder="Enter operation description"
                                className="om-op-desc-field__input w-full"
                                onChange={(e) => updateOp(row._rowId, "Operation", e.target.value)}
                              />
                              <div className="om-op-desc-field__actions">
                                <Button
                                  type="button"
                                  icon={hasInstruction ? "pi pi-file-edit" : "pi pi-align-left"}
                                  className={`om-op-instruction-btn${hasInstruction ? " om-op-instruction-btn--filled" : ""}`}
                                  rounded
                                  text
                                  size="small"
                                  tooltip={hasInstruction ? "Edit instruction" : "Add instruction"}
                                  tooltipOptions={{ position: "top" }}
                                  aria-label={hasInstruction ? "Edit instruction" : "Add instruction"}
                                  onClick={(event) => {
                                    event.preventDefault();
                                    event.stopPropagation();
                                    openInstruction(row);
                                  }}
                                />
                                {hasInstruction ? (
                                  <span className="om-op-instruction-dot" aria-hidden />
                                ) : null}
                              </div>
                            </div>
                          );
                        }}
                      />
                      <Column
                        header="Setup Time"
                        style={{ minWidth: "8rem", width: "8rem" }}
                        body={(row) => (
                          <InputNumber
                            value={row["Setup Time"]}
                            min={0}
                            mode="decimal"
                            minFractionDigits={0}
                            maxFractionDigits={2}
                            className="w-full"
                            onValueChange={(e) => updateOp(row._rowId, "Setup Time", e.value)}
                          />
                        )}
                      />
                      <Column
                        header="Per Piece Time"
                        style={{ minWidth: "9rem", width: "9rem" }}
                        body={(row) => (
                          <InputNumber
                            value={row["Per Pc Time"]}
                            min={0}
                            mode="decimal"
                            minFractionDigits={0}
                            maxFractionDigits={2}
                            className="w-full"
                            onValueChange={(e) => updateOp(row._rowId, "Per Pc Time", e.value)}
                          />
                        )}
                      />
                      <Column
                        header="Requires input"
                        style={{ minWidth: "8.5rem", width: "8.5rem" }}
                        body={(row) => (
                          <div className="om-create-order-op-flag">
                            <Checkbox
                              inputId={`${row._rowId}-in`}
                              binary
                              checked={Boolean(row.requires_input_material)}
                              onChange={(e) =>
                                updateOp(row._rowId, "requires_input_material", e.checked)
                              }
                            />
                            <label htmlFor={`${row._rowId}-in`}>input</label>
                          </div>
                        )}
                      />
                      <Column
                        header="Generate o/p"
                        style={{ minWidth: "8.5rem", width: "8.5rem" }}
                        body={(row) => (
                          <div className="om-create-order-op-flag">
                            <Checkbox
                              inputId={`${row._rowId}-out`}
                              binary
                              checked={Boolean(row.generates_output_serial)}
                              onChange={(e) =>
                                updateOp(row._rowId, "generates_output_serial", e.checked)
                              }
                            />
                            <label htmlFor={`${row._rowId}-out`}>o/p</label>
                          </div>
                        )}
                      />
                      <Column
                        header="Manual"
                        style={{ minWidth: "7rem", width: "7rem" }}
                        body={(row) => (
                          <div className="om-create-order-op-flag">
                            <Checkbox
                              inputId={`${row._rowId}-man`}
                              binary
                              checked={row.manual_operation !== false}
                              onChange={(e) => updateOp(row._rowId, "manual_operation", e.checked)}
                            />
                            <label htmlFor={`${row._rowId}-man`}>manual</label>
                          </div>
                        )}
                      />
                      <Column
                        header="Actions"
                        style={{ minWidth: "6rem", width: "6rem" }}
                        body={(row) => (
                          <Button
                            type="button"
                            label="Delete"
                            severity="danger"
                            text
                            size="small"
                            onClick={() => deleteOp(row._rowId)}
                          />
                        )}
                      />
                    </DataTable>
                  </div>
                </TabPanel>

                <TabPanel header="Raw Materials">
                  <div className="om-create-order-section">
                    <div className="om-create-order-section__toolbar">
                      <span className="om-create-order-section__hint">
                        {rawMaterials.length
                          ? "Edit raw materials data below:"
                          : "No raw materials found. Click 'Add Material' to add a new material:"}
                      </span>
                      <Button
                        type="button"
                        label="Add Material"
                        size="small"
                        onClick={() => setRawMaterials((rows) => [...rows, emptyRawMaterial(rows)])}
                      />
                    </div>
                    <DataTable
                      value={rawMaterials}
                      dataKey="_rowId"
                      scrollable
                      scrollHeight="360px"
                      tableStyle={{ minWidth: "64rem" }}
                      className="om-create-order-table"
                      emptyMessage={
                        <div className="om-create-order-empty">
                          <p>No raw materials added yet.</p>
                          <p className="om-create-order-empty__sub">
                            Click &quot;Add Material&quot; to add a new material.
                          </p>
                        </div>
                      }
                    >
                      <Column
                        header="Sl. No"
                        style={{ minWidth: "6.5rem", width: "6.5rem" }}
                        body={(row) => (
                          <InputNumber
                            value={row["Sl.No"]}
                            min={1}
                            className="w-full"
                            onValueChange={(e) => updateMat(row._rowId, "Sl.No", e.value)}
                          />
                        )}
                      />
                      <Column
                        header="Part Number"
                        style={{ minWidth: "12rem" }}
                        body={(row) => (
                          <InputText
                            value={row["Child Part No"]}
                            className="w-full"
                            onChange={(e) => updateMat(row._rowId, "Child Part No", e.target.value)}
                          />
                        )}
                      />
                      <Column
                        header="Description"
                        style={{ minWidth: "22rem" }}
                        body={(row) => (
                          <InputText
                            value={row.Description}
                            className="w-full"
                            onChange={(e) => updateMat(row._rowId, "Description", e.target.value)}
                          />
                        )}
                      />
                      <Column
                        header="Quantity Per Set"
                        style={{ minWidth: "9rem", width: "9rem" }}
                        body={(row) => (
                          <InputNumber
                            value={row["Qty Per Set"]}
                            className="w-full"
                            onValueChange={(e) => updateMat(row._rowId, "Qty Per Set", e.value)}
                          />
                        )}
                      />
                      <Column
                        header="UoM"
                        style={{ minWidth: "6rem", width: "6rem" }}
                        body={(row) => (
                          <InputText
                            value={row.UoM}
                            className="w-full"
                            onChange={(e) => updateMat(row._rowId, "UoM", e.target.value)}
                          />
                        )}
                      />
                      <Column
                        header="Total Quantity"
                        style={{ minWidth: "9rem", width: "9rem" }}
                        body={(row) => (
                          <InputNumber value={row["Total Qty"]} className="w-full" disabled />
                        )}
                      />
                      <Column
                        header="Actions"
                        style={{ minWidth: "6rem", width: "6rem" }}
                        body={(row) => (
                          <Button
                            type="button"
                            label="Delete"
                            severity="danger"
                            text
                            size="small"
                            onClick={() =>
                              setRawMaterials((rows) => rows.filter((r) => r._rowId !== row._rowId))
                            }
                          />
                        )}
                      />
                    </DataTable>
                  </div>
                </TabPanel>

                <TabPanel header="Documents">
                  <div className="om-create-order-section">
                    <div className="om-create-order-section__toolbar">
                      <span className="om-create-order-section__hint">
                        Document Information — prefilled from uploaded Drawing and Parts List.
                      </span>
                    </div>
                    <div className="grid">
                      <div className="col-12 md:col-6">
                        <div className="om-create-order-card">
                          <div className="om-create-order-card__header">
                            <span className="om-create-order-card__title">Engineering Drawing</span>
                            <i className="pi pi-file-pdf" style={{ color: "var(--pmf-accent)" }} />
                          </div>
                          <div className="om-create-order-card__body">
                            <div className="field">
                              <label>Document Name *</label>
                              <InputText
                                className="w-full om-input"
                                value={drawingMeta.name}
                                onChange={(e) => setDrawingMeta((m) => ({ ...m, name: e.target.value }))}
                                placeholder="Enter document name"
                              />
                            </div>
                            <div className="field">
                              <label>Description</label>
                              <InputTextarea
                                className="w-full"
                                rows={2}
                                value={drawingMeta.description}
                                onChange={(e) =>
                                  setDrawingMeta((m) => ({ ...m, description: e.target.value }))
                                }
                                placeholder="Enter description"
                              />
                            </div>
                            <div className="field">
                              <label>Version *</label>
                              <InputText
                                className="w-full om-input"
                                value={drawingMeta.version}
                                onChange={(e) =>
                                  setDrawingMeta((m) => ({ ...m, version: e.target.value }))
                                }
                              />
                            </div>
                            <Button
                              type="button"
                              className="w-full"
                              icon="pi pi-upload"
                              label={drawingMeta.fileName ? drawingMeta.fileName : "Select Drawing File"}
                              outlined={!drawingMeta.fileName}
                              disabled
                            />
                            <p className="om-create-order-file-debug">
                              File selected:{" "}
                              {drawingMeta.fileName ? `Yes — ${drawingMeta.fileName}` : "No"}
                            </p>
                          </div>
                        </div>
                      </div>
                      <div className="col-12 md:col-6">
                        <div className="om-create-order-card">
                          <div className="om-create-order-card__header">
                            <span className="om-create-order-card__title">Part List</span>
                            <i className="pi pi-list" style={{ color: "var(--pmf-accent)" }} />
                          </div>
                          <div className="om-create-order-card__body">
                            <div className="field">
                              <label>Document Name *</label>
                              <InputText
                                className="w-full om-input"
                                value={plMeta.name}
                                onChange={(e) => setPlMeta((m) => ({ ...m, name: e.target.value }))}
                                placeholder="Enter document name"
                              />
                            </div>
                            <div className="field">
                              <label>Description</label>
                              <InputTextarea
                                className="w-full"
                                rows={2}
                                value={plMeta.description}
                                onChange={(e) =>
                                  setPlMeta((m) => ({ ...m, description: e.target.value }))
                                }
                                placeholder="Enter description"
                              />
                            </div>
                            <div className="field">
                              <label>Version *</label>
                              <InputText
                                className="w-full om-input"
                                value={plMeta.version}
                                onChange={(e) => setPlMeta((m) => ({ ...m, version: e.target.value }))}
                              />
                            </div>
                            <Button
                              type="button"
                              className="w-full"
                              icon="pi pi-upload"
                              label={plMeta.fileName ? plMeta.fileName : "Select Part List"}
                              outlined={!plMeta.fileName}
                              disabled
                            />
                            <p className="om-create-order-file-debug">
                              File selected: {plMeta.fileName ? `Yes — ${plMeta.fileName}` : "No"}
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </TabPanel>
              </TabView>
            </div>
          </div>
        )}
      </Dialog>

      <Dialog
        header={instr.title || "Operation instruction"}
        visible={instr.visible}
        onHide={() => setInstr(emptyInstr())}
        className="oarc-instr-dialog"
        style={{ width: "min(92vw, 28rem)" }}
        footer={
          <div className="oarc-instr-dialog__footer">
            <Button
              type="button"
              label="Cancel"
              outlined
              size="small"
              onClick={() => setInstr(emptyInstr())}
            />
            <Button type="button" label="Save" icon="pi pi-check" size="small" onClick={saveInstruction} />
          </div>
        }
      >
        <p className="oarc-instr-dialog__hint">Operator instructions (printed on OARC).</p>
        <InputTextarea
          value={instr.draft}
          onChange={(e) => setInstr((s) => ({ ...s, draft: e.target.value }))}
          rows={6}
          className="w-full oarc-instr-dialog__textarea"
          autoResize
        />
        {(instr.itemsUsed?.length > 0 || instr.reference || instr.torqueSpec) && (
          <div className="oarc-instr-dialog__meta" aria-label="Reference only — not printed">
            <Tooltip target=".oarc-instr-chip--item" position="top" showDelay={120} />
            <span className="oarc-instr-dialog__meta-label">Ref:</span>
            <div className="oarc-instr-dialog__chips">
              {(instr.itemsUsed || []).map((item, idx) => {
                const hit = itemLookup[String(item.itemNo)] || {};
                const name = item.description || hit.description || hit.designation || "";
                const partNo = item.partNumber || hit.partNumber || hit.part_number || "";
                const tip =
                  [name, partNo].filter(Boolean).join(" · ") ||
                  `Item #${item.itemNo} (upload Parts List for name)`;
                return (
                  <span
                    key={`${item.itemNo}-${idx}`}
                    className="oarc-instr-chip oarc-instr-chip--item"
                    data-pr-tooltip={tip}
                    data-pr-position="top"
                  >
                    #{item.itemNo}
                    {item.qty != null && item.qty !== "" ? `×${item.qty}` : ""}
                  </span>
                );
              })}
              {instr.reference ? (
                <span className="oarc-instr-chip oarc-instr-chip--ref" title={instr.reference}>
                  Ref: {instr.reference}
                </span>
              ) : null}
              {instr.torqueSpec ? (
                <span className="oarc-instr-chip oarc-instr-chip--torque" title={instr.torqueSpec}>
                  Torque: {instr.torqueSpec}
                </span>
              ) : null}
            </div>
          </div>
        )}
      </Dialog>

      <OpTemplatePickerDialog
        visible={tplPickerOpen}
        onHide={() => setTplPickerOpen(false)}
        onSelect={addFromTemplate}
      />
    </>
  );
}
