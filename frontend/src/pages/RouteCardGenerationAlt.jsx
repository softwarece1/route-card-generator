import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "primereact/button";
import { Column } from "primereact/column";
import { DataTable } from "primereact/datatable";
import { Dialog } from "primereact/dialog";
import { InputText } from "primereact/inputtext";
import { InputTextarea } from "primereact/inputtextarea";
import { Message } from "primereact/message";
import { ProgressBar } from "primereact/progressbar";
import { TabPanel, TabView } from "primereact/tabview";
import { Tag } from "primereact/tag";
import { Tooltip } from "primereact/tooltip";
import { toast } from "@/lib/toast";
import {
  analyzeSession,
  createSession,
  deleteSessionDocument,
  fetchDrawingFileBlob,
  fetchMachinesQuietly,
  learnFormatTemplate,
  saveRouteDraft,
  updateRouteCard,
  uploadSessionDocument,
} from "@/services/routeCardApi";
import OarcPreviewDialog from "@/components/OarcPreviewDialog";
import OpTemplatePickerDialog from "@/components/OpTemplatePickerDialog";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import {
  insertTemplateSteps,
  renumberRouteOps,
  templateStepToRouteOp,
} from "@/lib/pmfOrderPrefill";
import "@fontsource/rubik/400.css";
import "@fontsource/rubik/500.css";
import "@fontsource/rubik/600.css";
import "@fontsource/rubik/700.css";
import "@fontsource/rubik/800.css";
import "./route-card-generation-alt.scss";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

const UPLOAD_SLOTS = [
  {
    role: "drawing",
    title: "Drawing (GA)",
    hint: "PDF / TIFF · multiple GAs OK (Max 10 MB each)",
    accept: ".pdf,.tif,.tiff",
    required: true,
    icon: "pi-file",
    multiple: true,
  },
  {
    role: "partslist",
    title: "Parts List (PL)",
    hint: "PDF / Excel (.xls, .xlsx) (Max 10 MB)",
    accept: ".pdf,.xls,.xlsx",
    required: true,
    icon: "pi-list",
    multiple: false,
  },
  {
    role: "wirelist",
    title: "Wire List (WL)",
    hint: "PDF / Excel (.xls, .xlsx) (Max 10 MB)",
    accept: ".pdf,.xls,.xlsx",
    required: false,
    icon: "pi-sitemap",
    multiple: false,
  },
];

/** End-user banner text only — hide OCR / drawing-mind internals. */
function toUserFacingWarnings(list) {
  const warnings = Array.isArray(list) ? list : [];
  const technical =
    /tesseract|drawing\s*mind|local_vlm|\bocr\b|balloon|cpu\)|gpu|spatial|pdfplumber|pymupdf|pypdf|low-confidence|note order|item balloon/i;
  let plIssue = false;
  let wlIssue = false;
  const out = [];
  for (const raw of warnings) {
    const w = String(raw || "").trim();
    if (!w) continue;
    const low = w.toLowerCase();
    if (technical.test(w)) continue;
    if (low.includes("wire list not provided") || low.includes("continuity checklist skipped")) continue;
    if (low.includes("parts list not provided")) {
      plIssue = true;
      continue;
    }
    if (low.includes("parts list") && (low.includes("plain text") || low.includes("parsed as") || low.includes("tsv"))) {
      continue;
    }
    if (low.includes("wire list") && (low.includes("plain text") || low.includes("parsed as") || low.includes("tsv"))) {
      continue;
    }
    if (
      low.includes("parts list") &&
      ["no item", "could not", "failed", "expected columns", "little/no text", "not match", "no item rows"].some(
        (k) => low.includes(k)
      )
    ) {
      plIssue = true;
      continue;
    }
    if (low.includes("could not open as excel") || low.includes("openpyxl") || low.includes("xlrd is not installed")) {
      plIssue = true;
      continue;
    }
    if (
      low.includes("wire list") &&
      ["could not", "failed", "few/no", "little/no", "prefer a clean", "unsupported"].some((k) => low.includes(k))
    ) {
      wlIssue = true;
      continue;
    }
    if (low.includes("wire list part number") && low.includes("differs")) {
      out.push("Wire List part number does not match the drawing. Please verify the files.");
      continue;
    }
    if (w.length > 180) continue;
    out.push(w);
  }
  if (plIssue) {
    out.unshift(
      "Parts List could not be read or does not match the expected format. Please upload a valid PDF or Excel Parts List."
    );
  }
  if (wlIssue) {
    out.push(
      "Wire List could not be read or does not match the expected format. Please upload a valid PDF or Excel Wire List."
    );
  }
  return [...new Set(out)];
}

const EMPTY_OPERATION = {
  operation: "",
  workCentre: "",
  machine: "",
  tool: "",
  items: "",
  torqueSpec: "",
  reference: "",
  setup: "1",
  time: "",
  inspection: "—",
  instructionText: "",
  status: "Planned",
};

const ANALYSIS_LABELS = {
  ocr: "Text extraction",
  notes: "Assembly notes",
  bom: "BOM callouts",
  torque: "Torque / standards",
  dims: "Interface dimensions",
  mind: "Drawing mind",
  wl: "Wire List",
  pl: "Parts List",
  route: "Route generation",
};

function formatBytes(bytes) {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Map drawing-intelligence level labels → PrimeReact Tag severity */
function levelSeverity(level) {
  const t = String(level || "").toLowerCase();
  if (t.includes("critic")) return "danger";
  if (t.includes("import")) return "warning";
  if (t.includes("std") || t.includes("standard") || t.includes("normal")) return "info";
  return "secondary";
}

/** Work-centre / op-type chip color */
function workCentreSeverity(type) {
  const t = String(type || "").toLowerCase();
  if (t.includes("torque")) return "warning";
  if (t.includes("bond") || t.includes("glue") || t.includes("adhes")) return "info";
  if (t.includes("quality") || t.includes("inspect")) return "success";
  if (t.includes("pcb")) return "info";
  if (t.includes("special")) return "warning";
  return "secondary";
}

function nextOpNumber(rows) {
  const nums = rows.map((r) => Number(r.opNo)).filter((n) => Number.isFinite(n));
  if (!nums.length) return 10;
  return Math.floor(Math.max(...nums) / 10) * 10 + 10;
}

function OpItemsList({ itemsUsed, fallback, itemLookup = {} }) {
  const rows = (Array.isArray(itemsUsed) ? itemsUsed : []).filter((i) => i?.itemNo != null);
  if (rows.length === 0) {
    return fallback ? <div className="rca-op__features">{fallback}</div> : null;
  }
  return (
    <div className="rca-op__items">
      {rows.map((item, idx) => {
        const hit = itemLookup[String(item.itemNo)] || {};
        const name = item.description || hit.description || "";
        const partNo = item.partNumber || hit.partNumber || "";
        const tip =
          [name, partNo].filter(Boolean).join(" · ") ||
          `Item #${item.itemNo} (upload Parts List for name)`;
        return (
          <span key={`${item.itemNo}-${idx}`}>
            <span className="rca-op__item" data-pr-tooltip={tip} data-pr-position="top">
              <span className="rca-op__item-no">#{item.itemNo}</span>
              {item.qty != null && item.qty !== "" ? (
                <span className="rca-op__item-qty"> ×{item.qty}</span>
              ) : null}
            </span>
            {idx < rows.length - 1 ? ", " : null}
          </span>
        );
      })}
    </div>
  );
}

function DrawingPreview({ url, fileType }) {
  const kind = String(fileType || "").toUpperCase();
  if (url && kind === "PDF") {
    return (
      <object className="rca-pdf" data={url} type="application/pdf" aria-label="Engineering drawing PDF">
        <p className="rca-preview-fallback">PDF preview is not available in this browser.</p>
      </object>
    );
  }
  if (url && (kind === "TIF" || kind === "TIFF")) {
    return (
      <img className="rca-pdf" src={url} alt="Engineering drawing TIFF" />
    );
  }
  return (
    <div className="rca-preview-missing">
      <i className="pi pi-file" />
      <span>{fileType || "FILE"} stored — preview is available for PDF and TIFF.</span>
    </div>
  );
}

function SectionHead({ title, badge, actionLabel, onAction, primaryAction }) {
  return (
    <div className="rca-section-head">
      <div className="rca-section-head__left">
        <span>{title}</span>
      </div>
      <div className="rca-section-head__right">
        {badge}
        {actionLabel ? (
          <Button type="button" label={actionLabel} link size="small" onClick={onAction} />
        ) : null}
        {primaryAction}
      </div>
    </div>
  );
}

export default function RouteCardGenerationAlt() {
  const fileInputRefs = useRef({});

  const [sessionId, setSessionId] = useState(null);
  const [docs, setDocs] = useState({ drawing: null, drawings: [], wirelist: null, partslist: null });
  const [resultTab, setResultTab] = useState(0);
  const [dragRole, setDragRole] = useState(null);
  const [drawingId, setDrawingId] = useState(null);
  const [routeCardId, setRouteCardId] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzed, setAnalyzed] = useState(false);
  const [taskProgress, setTaskProgress] = useState({});
  const [warnings, setWarnings] = useState([]);
  const [drawingInfo, setDrawingInfo] = useState({});
  const [bomItems, setBomItems] = useState([]);
  const [featureCounts, setFeatureCounts] = useState([]);
  const [intelDims, setIntelDims] = useState([]);
  const [intelReqs, setIntelReqs] = useState([]);
  const [suggestedOps, setSuggestedOps] = useState([]);
  const [routeOps, setRouteOps] = useState([]);
  const [inspectionChars, setInspectionChars] = useState([]);
  const [revisions, setRevisions] = useState([]);
  const [partsListSummary, setPartsListSummary] = useState(null);
  const [wireListSummary, setWireListSummary] = useState(null);
  const [machines, setMachines] = useState([]);
  const [reviewStatus, setReviewStatus] = useState("ready");
  const [editVisible, setEditVisible] = useState(false);
  const [editRow, setEditRow] = useState(null);
  const [editIsNew, setEditIsNew] = useState(false);
  const [uploadingRole, setUploadingRole] = useState(null);
  const [savingFormat, setSavingFormat] = useState(null);
  const [analysisPayload, setAnalysisPayload] = useState(null);
  const [oarcPreviewOpen, setOarcPreviewOpen] = useState(false);
  const [tplPickerOpen, setTplPickerOpen] = useState(false);
  const [extractedNotes, setExtractedNotes] = useState([]);
  const [mindInfo, setMindInfo] = useState(null);
  const [crossRefs, setCrossRefs] = useState([]);

  const hasGa = Boolean(docs.drawing || (docs.drawings && docs.drawings.length));
  const canAnalyze = Boolean(hasGa && docs.partslist && drawingId && !analyzing && !uploadingRole);
  const showResults = analyzed && !analyzing;

  const applyPayload = useCallback((payload) => {
    if (!payload) return;
    setAnalysisPayload(payload);
    setRouteCardId(payload.id ?? null);
    if (payload.drawing?.id) setDrawingId(payload.drawing.id);
    if (payload.sessionId) setSessionId(payload.sessionId);
    setDrawingInfo(payload.drawingInfo || {});
    setBomItems(payload.bomItems || []);
    setFeatureCounts(payload.featureCounts || []);
    setIntelDims(payload.intelligenceDimensions || []);
    setIntelReqs(payload.intelligenceRequirements || []);
    setSuggestedOps(payload.suggestedOperations || []);
    setRouteOps(payload.routeOperations || []);
    setInspectionChars(payload.inspectionChars || []);
    setRevisions(payload.revisions || []);
    setWireListSummary(payload.wireList || null);
    setPartsListSummary(payload.partsList || null);
    setWarnings(toUserFacingWarnings(payload.warnings || payload.drawing?.warnings || []));
    setExtractedNotes(payload.notes || []);
    setMindInfo({
      ...(payload.mind || {}),
      warnings: [],
      viewRefs: payload.viewRefs || payload.mind?.viewRefs || [],
    });
    setCrossRefs(payload.crossRefs || payload.mind?.crossRefs || []);
    if (payload.status === "approved") setReviewStatus("approved");
    else if (payload.status === "draft") setReviewStatus("draft");
    const tasks = payload.analysisTasks || [];
    setTaskProgress(Object.fromEntries(tasks.map((t) => [t.key, t.value ?? 100])));
  }, []);

  const clearPreview = useCallback(() => {
    setPreviewUrl((url) => {
      if (url) URL.revokeObjectURL(url);
      return null;
    });
  }, []);

  useEffect(() => () => clearPreview(), [clearPreview]);

  useEffect(() => {
    let cancelled = false;
    fetchMachinesQuietly().then((rows) => {
      if (!cancelled) setMachines(rows);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const plItemLookup = useMemo(() => {
    const map = {};
    for (const it of partsListSummary?.items || []) {
      if (it?.itemNo == null) continue;
      map[String(it.itemNo)] = it;
    }
    for (const it of bomItems || []) {
      if (it?.itemNo == null || !it.description) continue;
      const key = String(it.itemNo);
      map[key] = { ...map[key], ...it };
    }
    return map;
  }, [partsListSummary, bomItems]);

  const ensureSession = async () => {
    if (sessionId) return sessionId;
    const s = await createSession();
    setSessionId(s.id);
    return s.id;
  };

  const loadPreview = async (id, type) => {
    const kind = String(type || "").toUpperCase();
    if (!["PDF", "TIF", "TIFF"].includes(kind)) {
      clearPreview();
      return;
    }
    try {
      const blob = await fetchDrawingFileBlob(id);
      clearPreview();
      setPreviewUrl(URL.createObjectURL(blob));
    } catch {
      clearPreview();
    }
  };

  /** Clear UI only — session is created lazily on next upload. */
  const resetPage = () => {
    clearPreview();
    setDocs({ drawing: null, drawings: [], wirelist: null, partslist: null });
    setDrawingId(null);
    setRouteCardId(null);
    setSessionId(null);
    setZoom(1);
    setAnalyzing(false);
    setAnalyzed(false);
    setTaskProgress({});
    setWarnings([]);
    setDrawingInfo({});
    setBomItems([]);
    setFeatureCounts([]);
    setIntelDims([]);
    setIntelReqs([]);
    setSuggestedOps([]);
    setRouteOps([]);
    setInspectionChars([]);
    setRevisions([]);
    setWireListSummary(null);
    setPartsListSummary(null);
    setExtractedNotes([]);
    setMindInfo(null);
    setCrossRefs([]);
    setReviewStatus("ready");
    setResultTab(0);
    toast.success("Page reset.");
  };

  const syncDocsFromSession = (documents = [], drawingIds = []) => {
    const drawings = (documents || [])
      .filter((d) => d.role === "drawing")
      .map((d) => ({
        id: d.id,
        drawingId: d.drawingId || null,
        name: d.filename,
        type: d.file_type,
        sizeLabel: d.size_label,
        sizeBytes: d.size_bytes,
        status: d.status,
        role: "drawing",
      }));
    const pl = (documents || []).find((d) => d.role === "partslist");
    const wl = (documents || []).find((d) => d.role === "wirelist");
    setDocs({
      drawings,
      drawing: drawings.length ? drawings[drawings.length - 1] : null,
      partslist: pl
        ? {
            id: pl.id,
            name: pl.filename,
            type: pl.file_type,
            sizeLabel: pl.size_label,
            sizeBytes: pl.size_bytes,
            status: pl.status,
            role: "partslist",
          }
        : null,
      wirelist: wl
        ? {
            id: wl.id,
            name: wl.filename,
            type: wl.file_type,
            sizeLabel: wl.size_label,
            sizeBytes: wl.size_bytes,
            status: wl.status,
            role: "wirelist",
          }
        : null,
    });
    if (drawingIds?.length) setDrawingId(drawingIds[drawingIds.length - 1]);
  };

  const applySlotFile = async (role, file) => {
    if (!file) return;
    const slot = UPLOAD_SLOTS.find((s) => s.role === role);
    const slotTitle = slot?.title || role;
    const ext = `.${(file.name.split(".").pop() || "").toLowerCase()}`;
    const allowed = (slot?.accept || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    if (allowed.length && !allowed.includes(ext)) {
      toast.error(
        `${slotTitle}: unsupported type ${ext || "(none)"}. Allowed: ${allowed.join(", ")}`
      );
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      toast.error(`${slotTitle}: file exceeds 10 MB limit`);
      return;
    }
    setUploadingRole(role);
    toast.info(`Uploading ${slotTitle}…`);
    try {
      const sid = await ensureSession();
      const meta = await uploadSessionDocument(sid, role, file);
      syncDocsFromSession(meta.documents || [], meta.drawingIds || (meta.drawingId ? [meta.drawingId] : []));
      if (meta.drawingId) {
        setDrawingId(meta.drawingId);
        if (role === "drawing") {
          const type = meta.document?.file_type || file.name.split(".").pop()?.toUpperCase();
          await loadPreview(meta.drawingId, type);
        }
      }
      setAnalyzed(false);
      setAnalyzing(false);
      setTaskProgress({});
      setResultTab(0);
      setReviewStatus("ready");
      setRouteOps([]);
      setRouteCardId(null);
      toast.success(`${slotTitle} uploaded.`);
    } catch (error) {
      toast.error(error.message || "Upload failed");
    } finally {
      setUploadingRole(null);
    }
  };

  const applySlotFiles = async (role, fileList) => {
    const files = Array.from(fileList || []).filter(Boolean);
    if (!files.length) return;
    if (role !== "drawing" || files.length === 1) {
      await applySlotFile(role, files[0]);
      return;
    }
    for (const f of files) {
      // Sequential so session state stays consistent
      // eslint-disable-next-line no-await-in-loop
      await applySlotFile(role, f);
    }
  };

  const removeSlot = async (role, documentId = null) => {
    try {
      if (sessionId) {
        const meta = await deleteSessionDocument(sessionId, role, documentId);
        syncDocsFromSession(meta.documents || [], meta.drawingIds || []);
        if (meta.drawingId) {
          setDrawingId(meta.drawingId);
          const last = (meta.documents || []).filter((d) => d.role === "drawing").pop();
          if (last) await loadPreview(meta.drawingId, last.file_type);
          else clearPreview();
        } else if (role === "drawing") {
          setDrawingId(null);
          clearPreview();
        }
      } else {
        setDocs((prev) => {
          if (role === "drawing" && documentId != null) {
            const drawings = (prev.drawings || []).filter((d) => d.id !== documentId);
            return {
              ...prev,
              drawings,
              drawing: drawings.length ? drawings[drawings.length - 1] : null,
            };
          }
          if (role === "drawing") {
            return { ...prev, drawing: null, drawings: [] };
          }
          return { ...prev, [role]: null };
        });
        if (role === "drawing") {
          clearPreview();
          setDrawingId(null);
        }
      }
    } catch {
      setDocs((prev) => {
        if (role === "drawing" && documentId != null) {
          const drawings = (prev.drawings || []).filter((d) => d.id !== documentId);
          return {
            ...prev,
            drawings,
            drawing: drawings.length ? drawings[drawings.length - 1] : null,
          };
        }
        return { ...prev, [role]: null, ...(role === "drawing" ? { drawings: [] } : {}) };
      });
      if (role === "drawing") {
        clearPreview();
        setDrawingId(null);
      }
    }
    setAnalyzed(false);
    setRouteOps([]);
    setRouteCardId(null);
    setWarnings([]);
    setAnalysisPayload(null);
    setResultTab(0);
  };

  const runAnalysis = async () => {
    if (!sessionId || !hasGa || analyzing) return;
    setAnalyzing(true);
    setAnalyzed(false);
    setResultTab(0);
    setTaskProgress({
      ocr: 20,
      notes: 10,
      bom: 10,
      torque: 10,
      dims: 10,
      mind: 10,
      wl: docs.wirelist ? 15 : 0,
      pl: docs.partslist ? 15 : 0,
      route: 5,
    });
    try {
      const payload = await analyzeSession(sessionId);
      applyPayload(payload);
      setAnalyzing(false);
      setAnalyzed(true);
      setResultTab(1);
      toast.success("OARC generated. Review the results in the tabs below.");
    } catch (error) {
      setAnalyzing(false);
      toast.error(error.message || "Analysis failed");
    }
  };

  const persistOps = async (rows) => {
    if (!routeCardId) {
      setRouteOps(rows);
      return;
    }
    try {
      const payload = await updateRouteCard(routeCardId, {
        operations: rows,
        inspection: inspectionChars,
      });
      applyPayload(payload);
    } catch (error) {
      toast.error(error.message || "Could not save operations");
      setRouteOps(rows);
    }
  };

  const openEdit = (row) => {
    if (row) {
      setEditIsNew(false);
      setEditRow({ ...row });
    } else {
      setEditIsNew(true);
      setEditRow({ ...EMPTY_OPERATION, id: `op-${Date.now()}`, opNo: nextOpNumber(routeOps) });
    }
    setEditVisible(true);
  };

  const saveEdit = async () => {
    if (!editRow?.operation) {
      toast.warn("Operation name is required.");
      return;
    }
    const exists = !editIsNew && routeOps.some((r) => String(r.id) === String(editRow.id));
    const rows = exists
      ? routeOps.map((r) => (String(r.id) === String(editRow.id) ? editRow : r))
      : [...routeOps, editRow].sort((a, b) => Number(a.opNo) - Number(b.opNo));
    setEditVisible(false);
    setEditIsNew(false);
    await persistOps(rows);
    toast.success(exists ? "Route operation updated." : "Route operation added.");
  };

  const removeOp = async (row) => {
    await persistOps(routeOps.filter((r) => String(r.id) !== String(row.id)));
    toast.info(`Removed OP ${row.opNo}.`);
  };

  const addFromTemplate = async (tpl) => {
    const merged = insertTemplateSteps(
      routeOps,
      tpl?.steps || [],
      tpl?.placement,
      templateStepToRouteOp,
    );
    const next = renumberRouteOps(merged);
    await persistOps(next);
    toast.success(
      `Inserted ${(tpl?.steps || []).length} operation(s) from "${tpl?.name || "template"}"`,
    );
  };

  const saveDraft = async () => {
    if (!routeCardId) {
      toast.warn("Analyze a drawing first.");
      return;
    }
    try {
      const payload = await saveRouteDraft(routeCardId);
      applyPayload(payload);
      setReviewStatus("draft");
      toast.success("Draft saved.");
    } catch (error) {
      toast.error(error.message || "Save failed");
    }
  };

  const saveFormat = async (role) => {
    if (!sessionId) {
      toast.warn("No upload session.");
      return;
    }
    const docType = { drawing: "GA", wirelist: "WL", partslist: "PL" }[role] || "GA";
    const label = { drawing: "GA drawing", wirelist: "Wire List", partslist: "Parts List" }[role] || role;
    setSavingFormat(role);
    try {
      const res = await learnFormatTemplate(sessionId, {
        role,
        docType,
        name: `${label} — ${drawingInfo?.partNumber || drawingInfo?.drawingNumber || `session ${sessionId}`}`,
        notes: "Saved after engineer review",
      });
      toast.success(res.message || `Saved ${label} format template`);
    } catch (error) {
      toast.error(error.message || "Could not save format");
    } finally {
      setSavingFormat(null);
    }
  };

  const infoRows = [
    ["Drawing Number", drawingInfo.drawingNumber],
    ["Part Name", drawingInfo.partName],
    ["Revision", drawingInfo.version || drawingInfo.revision],
    ["Doc Type", drawingInfo.docType || "GA"],
    ["Sheets", drawingInfo.sheets],
    ["Material", drawingInfo.material],
    ["Weight", drawingInfo.weight],
    ["Overall Dimensions", drawingInfo.overallDimensions],
    ["Surface Finish", drawingInfo.surfaceFinish],
    ["Scale", drawingInfo.scale],
  ];

  const taskEntries = Object.keys(ANALYSIS_LABELS)
    .filter((k) => taskProgress[k] != null || showResults)
    .map((key) => ({
      key,
      label: ANALYSIS_LABELS[key],
      value: showResults ? taskProgress[key] ?? 100 : taskProgress[key] ?? 0,
    }));

  return (
    <AppShell active="generator">
      {UPLOAD_SLOTS.map((slot) => (
        <input
          key={slot.role}
          ref={(el) => {
            fileInputRefs.current[slot.role] = el;
          }}
          type="file"
          accept={slot.accept}
          multiple={Boolean(slot.multiple)}
          hidden
          onChange={(e) => {
            const files = e.target.files;
            if (files?.length && !uploadingRole) applySlotFiles(slot.role, files);
            e.target.value = "";
          }}
        />
      ))}

        <div className="rca-content">
          <PageHeader
            title="Generator"
            subtitle="Upload drawing and parts list documents, then generate and review the OARC route."
            icon="pi pi-home"
            actions={
              <>
                <Button
                  type="button"
                  label="Reset"
                  icon="pi pi-refresh"
                  size="small"
                  outlined
                  severity="secondary"
                  disabled={analyzing || !!uploadingRole}
                  onClick={resetPage}
                />
                <Button
                  type="button"
                  label={analyzing ? "Generating…" : "Generate OARC"}
                  icon="pi pi-bolt"
                  size="small"
                  loading={analyzing}
                  disabled={!canAnalyze}
                  onClick={runAnalysis}
                />
              </>
            }
          />
          {warnings.length > 0 && (
            <Message className="mb-3 w-full" severity="warn" text={warnings.join(" ")} />
          )}

          <section className="rca-card" id="rca-sec-upload">
            <SectionHead
              title="Upload Documents"
              badge={hasGa && docs.partslist ? <Tag value="Ready" severity="success" /> : null}
            />
            <p className="rca-card__intro">
              Upload one or more GA drawings for the same part family (cross-referenced GAs are merged).
              Parts List is required; Wire List is optional.
            </p>
            <div className="rca-upload-grid">
              {UPLOAD_SLOTS.map((slot) => {
                const multi = slot.role === "drawing";
                const drawings = docs.drawings || [];
                const file = multi ? (drawings.length ? drawings[drawings.length - 1] : null) : docs[slot.role];
                const filled = multi ? drawings.length > 0 : Boolean(file);
                const active = dragRole === slot.role;
                const uploading = uploadingRole === slot.role;
                return (
                  <div
                    key={slot.role}
                    className={`rca-slot${active ? " rca-slot--active" : ""}${filled ? " rca-slot--filled" : ""}${uploading ? " rca-slot--uploading" : ""}`}
                    onDragOver={(e) => {
                      e.preventDefault();
                      if (!uploading) setDragRole(slot.role);
                    }}
                    onDragLeave={() => setDragRole(null)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setDragRole(null);
                      if (uploading) return;
                      const list = e.dataTransfer.files;
                      if (list?.length) applySlotFiles(slot.role, list);
                    }}
                  >
                    <div className="rca-slot__head">
                      <div className="rca-slot__icon" aria-hidden="true">
                        <i className={`pi ${slot.icon}`} />
                      </div>
                      <div className="rca-slot__titles">
                        <strong>{slot.title}</strong>
                        <span className="rca-slot__hint">{slot.hint}</span>
                      </div>
                      {uploading ? (
                        <Tag value="Uploading…" severity="info" />
                      ) : slot.required ? (
                        <Tag value="Required" severity="danger" />
                      ) : (
                        <Tag value="Optional" severity="info" />
                      )}
                    </div>
                    <div className="rca-slot__body">
                      {!filled ? (
                        <div className="rca-slot__drop">
                          {!uploading && (
                            <>
                              <i className="pi pi-cloud-upload" aria-hidden="true" />
                              <p>{multi ? "Drag & drop one or more GAs here or" : "Drag & drop file here or"}</p>
                              <Button
                                type="button"
                                label="Browse File"
                                icon="pi pi-folder-open"
                                outlined
                                size="small"
                                onClick={() => fileInputRefs.current[slot.role]?.click()}
                              />
                            </>
                          )}
                        </div>
                      ) : multi ? (
                        <div className="rca-slot__file-list">
                          {drawings.map((g) => (
                            <div className="rca-slot__file" key={g.id || g.name}>
                              <i className="pi pi-file-pdf rca-slot__file-icon" aria-hidden="true" />
                              <div className="rca-slot__file-meta">
                                <strong title={g.name}>{g.name}</strong>
                                <span>{g.sizeLabel}</span>
                              </div>
                              <div className="rca-slot__actions">
                                <Button
                                  type="button"
                                  icon="pi pi-eye"
                                  rounded
                                  text
                                  size="small"
                                  disabled={uploading || !g.drawingId}
                                  aria-label="View drawing"
                                  onClick={async () => {
                                    if (g.drawingId) {
                                      setDrawingId(g.drawingId);
                                      await loadPreview(g.drawingId, g.type);
                                      setViewerOpen(true);
                                    }
                                  }}
                                />
                                <Button
                                  type="button"
                                  icon="pi pi-times"
                                  rounded
                                  text
                                  size="small"
                                  severity="secondary"
                                  disabled={uploading}
                                  aria-label={`Remove ${g.name}`}
                                  onClick={() => removeSlot("drawing", g.id)}
                                />
                              </div>
                            </div>
                          ))}
                          <Button
                            type="button"
                            label="Add another GA"
                            icon="pi pi-plus"
                            outlined
                            size="small"
                            className="mt-2"
                            disabled={uploading}
                            onClick={() => fileInputRefs.current[slot.role]?.click()}
                          />
                        </div>
                      ) : (
                        <div className="rca-slot__file">
                          <i className="pi pi-file-pdf rca-slot__file-icon" aria-hidden="true" />
                          <div className="rca-slot__file-meta">
                            <strong title={file.name}>{file.name}</strong>
                            <span>{uploading ? "Uploading replacement…" : file.sizeLabel}</span>
                          </div>
                          {uploading ? (
                            <i className="pi pi-spin pi-spinner rca-slot__spin" aria-hidden="true" />
                          ) : (
                            <i className="pi pi-check-circle rca-slot__ok" aria-hidden="true" />
                          )}
                          <div className="rca-slot__actions">
                            <Button
                              type="button"
                              icon="pi pi-times"
                              rounded
                              text
                              size="small"
                              severity="secondary"
                              disabled={uploading}
                              aria-label={`Remove ${slot.role}`}
                              onClick={() => removeSlot(slot.role)}
                            />
                          </div>
                        </div>
                      )}
                      {uploading ? (
                        <div className="rca-slot__overlay" aria-live="polite">
                          <i className="pi pi-spin pi-spinner" />
                          <span>Uploading…</span>
                          <span className="rca-slot__upload-hint">Please wait while the file is uploaded</span>
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
            {uploadingRole ? (
              <Message
                className="mt-3 w-full"
                severity="info"
                text={`Uploading ${UPLOAD_SLOTS.find((s) => s.role === uploadingRole)?.title || "file"}… Please wait.`}
              />
            ) : null}
            {!canAnalyze && !uploadingRole && (
              <Message
                className="mt-3 w-full"
                severity="info"
                text="Upload Drawing (GA) and Parts List to enable Generate OARC. Wire List is optional."
              />
            )}
          </section>

          <section className="rca-card" id="rca-sec-drawing">
            <SectionHead
              title="Drawing Preview & Information"
              actionLabel="View Full Details"
              onAction={() => setViewerOpen(true)}
            />
            <div className="rca-split">
              <div className="rca-viewer">
                <div className="rca-viewer__toolbar">
                  <span>Drawing preview</span>
                  <div className="rca-viewer__tools">
                    <Button type="button" icon="pi pi-minus" rounded text size="small" onClick={() => setZoom((z) => Math.max(0.5, z - 0.1))} />
                    <Button type="button" icon="pi pi-plus" rounded text size="small" onClick={() => setZoom((z) => Math.min(2, z + 0.1))} />
                    <Button type="button" icon="pi pi-window-maximize" rounded text size="small" onClick={() => setViewerOpen(true)} />
                  </div>
                </div>
                <div className="rca-viewer__canvas" style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}>
                  <DrawingPreview url={previewUrl} fileType={docs.drawing?.type} />
                </div>
              </div>
              <div className="rca-panel">
                <h3>Drawing Information</h3>
                <dl className="rca-info-grid">
                  {infoRows.map(([label, value]) => (
                    <div className="rca-kv" key={label}>
                      <dt>{label}</dt>
                      <dd>{value || "—"}</dd>
                    </div>
                  ))}
                </dl>
                {revisions?.length > 0 && (
                  <DataTable className="mt-3" value={revisions} size="small" paginator={false}>
                    <Column field="version" header="Ver" style={{ width: "4rem" }} />
                    <Column field="ecoNo" header="ECO" />
                    <Column field="relDate" header="Date" />
                  </DataTable>
                )}
              </div>
            </div>
          </section>

          <section className="rca-card rca-card--tabs">
            <TabView
              activeIndex={resultTab}
              onTabChange={(e) => setResultTab(e.index)}
              className="rca-result-tabs"
            >
              <TabPanel header="Analysis">
                <div id="rca-sec-analysis">
                  {!analyzed && !analyzing ? (
                    <Message severity="info" text="Upload documents and click Generate OARC to run document analysis." className="w-full" />
                  ) : (
                    <>
                      <div className="rca-tasks">
                        {taskEntries.map((task) => (
                          <div className="rca-task" key={task.key}>
                            <span>{task.label}</span>
                            <ProgressBar value={task.value} showValue={false} style={{ height: "0.55rem" }} />
                            <strong>{task.value}%</strong>
                          </div>
                        ))}
                      </div>
                      {showResults && mindInfo && (
                        <div className="rca-mind mt-3">
                          <h4 className="mb-2">
                            Drawing mind{" "}
                            <Tag value={mindInfo.engine || "cpu_spatial"} severity="info" />
                          </h4>
                          {(crossRefs || []).length > 0 && (
                            <DataTable className="mb-3" value={crossRefs} size="small" paginator={false}>
                              <Column field="drawingNumber" header="Referenced GA" />
                              <Column field="status" header="Status" />
                              <Column field="matchedFilename" header="Matched file" />
                            </DataTable>
                          )}
                          {(mindInfo.viewRefs || []).length > 0 && (
                            <DataTable className="mb-3" value={mindInfo.viewRefs} size="small" paginator={false}>
                              <Column field="label" header="View ref" />
                              <Column field="kind" header="Kind" style={{ width: "6rem" }} />
                              <Column field="status" header="Status" style={{ width: "7rem" }} />
                              <Column field="matchedFilename" header="Resolved file" />
                              <Column field="matchedSheet" header="Sheet" style={{ width: "5rem" }} />
                              <Column field="snippet" header="Detail" />
                            </DataTable>
                          )}
                          {(mindInfo.pcbLinks || []).length > 0 && (
                            <DataTable className="mb-3" value={mindInfo.pcbLinks} size="small" paginator={false}>
                              <Column field="connector" header="Connector" />
                              <Column field="plItemNo" header="PL item" />
                              <Column field="plDescription" header="Description" />
                              <Column field="wlWireCount" header="WL wires" />
                            </DataTable>
                          )}
                          {extractedNotes?.length > 0 && (
                            <div className="rca-notes">
                              <h4 className="mb-2">Elaborated instructions</h4>
                              {extractedNotes.map((n, idx) => (
                                <div className="rca-note" key={`${n.stepNo}-${idx}`}>
                                  <div className="rca-note__head">
                                    <strong>Step {n.stepNo}</strong>
                                    {n.elaboratedText ? (
                                      <Tag value="Elaborated" severity="success" />
                                    ) : null}
                                    {n.sourceFilename ? (
                                      <Tag value={n.sourceFilename} severity="secondary" />
                                    ) : null}
                                  </div>
                                  <p className="rca-note__text">
                                    {n.elaboratedText || n.text || "—"}
                                  </p>
                                  {n.elaboratedText && n.text && n.elaboratedText !== n.text ? (
                                    <p className="rca-note__source">Source: {n.text}</p>
                                  ) : null}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </TabPanel>

              <TabPanel header="BOM & Interface">
                <div id="rca-sec-bom">
                  {!showResults ? (
                    <Message severity="info" text="BOM and interface counts appear after analysis." className="w-full" />
                  ) : (
                    <>
                      <div className="rca-counts mb-3">
                        {(featureCounts.length
                          ? featureCounts
                          : [
                              { key: "bom", label: "BOM items", count: bomItems.length },
                              { key: "steps", label: "Assembly steps", count: suggestedOps.length },
                              { key: "wl", label: "Wire nets", count: wireListSummary?.wireCount || 0 },
                              { key: "pl", label: "PL items", count: partsListSummary?.items?.length || 0 },
                            ]
                        ).map((item) => (
                          <div className="rca-count" key={item.key || item.label}>
                            <strong>{item.count ?? item.value ?? 0}</strong>
                            <span>{item.label}</span>
                          </div>
                        ))}
                      </div>
                      <DataTable
                        className="rca-data-table"
                        value={bomItems}
                        size="small"
                        paginator
                        rows={10}
                        pageLinkSize={Math.max(1, Math.ceil((bomItems.length || 0) / 10))}
                        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport"
                        currentPageReportTemplate="{first}-{last} of {totalRecords}"
                        emptyMessage="No BOM items extracted."
                      >
                        <Column field="itemNo" header="Item" style={{ width: "6rem" }} />
                        <Column field="qty" header="Qty" style={{ width: "5rem" }} />
                        <Column field="partNumber" header="Part No." />
                        <Column field="description" header="Description" />
                      </DataTable>
                    </>
                  )}
                </div>
              </TabPanel>

              <TabPanel header="Drawing Intelligence">
                {!showResults ? (
                  <Message severity="info" text="Intelligence fields appear after analysis." className="w-full" />
                ) : (
                  <div className="rca-split">
                    <div className="rca-panel">
                      <h3>Dimensions / interfaces</h3>
                      {(intelDims || []).length === 0 ? (
                        <p style={{ margin: 0, color: "#64748b", fontSize: "0.85rem" }}>No dimension intelligence extracted.</p>
                      ) : (
                        (intelDims || []).map((item) => (
                          <div className="rca-kv mb-2" key={`${item.label}-${item.value}`}>
                            <dt>{item.label}</dt>
                            <dd>
                              {item.value}{" "}
                              {item.level ? (
                                <Tag className="ml-2" value={item.level} severity={levelSeverity(item.level)} />
                              ) : null}
                            </dd>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="rca-panel">
                      <h3>Requirements</h3>
                      {(intelReqs || []).length === 0 ? (
                        <p style={{ margin: 0, color: "#64748b", fontSize: "0.85rem" }}>No special requirements listed.</p>
                      ) : (
                        (intelReqs || []).map((item) => (
                          <div className="rca-kv mb-2" key={`${item.label}-${item.value}`}>
                            <dt>{item.label}</dt>
                            <dd>{item.value}</dd>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </TabPanel>

              <TabPanel header="Manufacturing Process">
                <div id="rca-sec-process">
                  {!showResults ? (
                    <Message severity="info" text="Suggested operations appear after analysis." className="w-full" />
                  ) : (
                    <>
                      <p className="rca-section-note">Sequence generated from the drawing NOTES blocks.</p>
                      <div className="rca-ops">
                        <Tooltip target=".rca-op__item" position="top" showDelay={150} />
                        {(suggestedOps || []).map((op) => (
                          <article className="rca-op" key={op.id || op.opNo}>
                            <div className="rca-op__top">
                              <div className="rca-op__no">OP {op.opNo}</div>
                              <Tag
                                value={op.type || op.workCentre || "Operation"}
                                severity={workCentreSeverity(op.type || op.workCentre)}
                              />
                            </div>
                            <h4>{op.operation}</h4>
                            <p className="rca-op__instr">
                              {op.elaborated ? (
                                <Tag value="Elaborated" severity="success" className="mr-2" />
                              ) : null}
                              {op.instructionText || op.reason || "—"}
                            </p>
                            <OpItemsList
                              itemsUsed={op.itemsUsed}
                              fallback={op.items}
                              itemLookup={plItemLookup}
                            />
                            <dl className="rca-op__meta">
                              {op.workCentre ? (
                                <div>
                                  <dt>Work centre</dt>
                                  <dd>{op.workCentre}</dd>
                                </div>
                              ) : null}
                              {op.machine ? (
                                <div>
                                  <dt>Machine</dt>
                                  <dd>{op.machine}</dd>
                                </div>
                              ) : null}
                              {op.tool ? (
                                <div>
                                  <dt>Tool</dt>
                                  <dd>{op.tool}</dd>
                                </div>
                              ) : null}
                              {op.torqueSpec ? (
                                <div>
                                  <dt>Torque / spec</dt>
                                  <dd>{op.torqueSpec}</dd>
                                </div>
                              ) : null}
                              {op.reference ? (
                                <div>
                                  <dt>Reference</dt>
                                  <dd>{op.reference}</dd>
                                </div>
                              ) : null}
                              {op.inspection ? (
                                <div>
                                  <dt>Inspection</dt>
                                  <dd>{op.inspection}</dd>
                                </div>
                              ) : null}
                            </dl>
                          </article>
                        ))}
                      </div>
                      {machines?.length > 0 && (
                        <div className="mt-3">
                          <h3 className="rca-subhead">Available machines</h3>
                          <p className="rca-section-note">
                            Plant machines from the MES register. Automatic capability matching is not enabled.
                          </p>
                          <div className="rca-machines">
                            {machines.slice(0, 6).map((machine) => (
                              <div className="rca-machine" key={machine.id || machine.name}>
                                <Tag value={machine.type || machine.machine_type || "Machine"} />
                                <h4>{machine.name || machine.machine_name || `Machine ${machine.id}`}</h4>
                                <p>Status: {machine.status || machine.machine_status || "—"}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </TabPanel>

              <TabPanel header="Route Card">
                <div id="rca-sec-route">
                  {!showResults ? (
                    <Message severity="info" text="Route operations appear after analysis." className="w-full" />
                  ) : (
                    <>
                      <div className="flex justify-content-end gap-2 mb-2">
                        <Button
                          type="button"
                          label="Add from template"
                          icon="pi pi-list"
                          outlined
                          size="small"
                          onClick={() => setTplPickerOpen(true)}
                        />
                        <Button type="button" label="Add operation" icon="pi pi-plus" outlined size="small" onClick={() => openEdit(null)} />
                      </div>
                      <DataTable
                        className="rca-data-table"
                        value={routeOps}
                        size="small"
                        paginator
                        rows={10}
                        pageLinkSize={Math.max(1, Math.ceil((routeOps.length || 0) / 10))}
                        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport"
                        currentPageReportTemplate="{first}-{last} of {totalRecords}"
                        emptyMessage="No operations."
                      >
                        <Column field="opNo" header="Op No." style={{ width: "5rem" }} />
                        <Column field="operation" header="Operation" />
                        <Column field="workCentre" header="Work centre" />
                        <Column field="machine" header="Machine" />
                        <Column
                          header=""
                          style={{ width: "7rem" }}
                          body={(row) => (
                            <div className="flex gap-1">
                              <Button type="button" icon="pi pi-pencil" rounded text size="small" onClick={() => openEdit(row)} />
                              <Button type="button" icon="pi pi-trash" rounded text size="small" severity="danger" onClick={() => removeOp(row)} />
                            </div>
                          )}
                        />
                      </DataTable>
                    </>
                  )}
                </div>
              </TabPanel>

              <TabPanel header="Quality & Inspection">
                <div id="rca-sec-quality">
                  {!showResults ? (
                    <Message severity="info" text="Inspection characteristics appear after analysis." className="w-full" />
                  ) : (
                    <DataTable
                      className="rca-data-table"
                      value={inspectionChars}
                      size="small"
                      paginator
                      rows={10}
                      pageLinkSize={Math.max(1, Math.ceil((inspectionChars.length || 0) / 10))}
                      paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport"
                      currentPageReportTemplate="{first}-{last} of {totalRecords}"
                      emptyMessage="No inspection rows."
                    >
                      <Column field="dimension" header="Characteristic" />
                      <Column field="nominal" header="Nominal" />
                      <Column field="tolerance" header="Tolerance" />
                      <Column field="method" header="Method" />
                      <Column field="frequency" header="Frequency" />
                      <Column field="criticality" header="Criticality" />
                    </DataTable>
                  )}
                </div>
              </TabPanel>

              <TabPanel
                header={
                  <span className="rca-tab-with-badge">
                    Engineer Review
                    <Tag
                      value={
                        reviewStatus === "approved"
                          ? "Approved"
                          : reviewStatus === "draft"
                            ? "Draft"
                            : "Pending"
                      }
                      severity={
                        reviewStatus === "approved"
                          ? "success"
                          : reviewStatus === "draft"
                            ? "warning"
                            : "secondary"
                      }
                    />
                  </span>
                }
              >
                <div id="rca-sec-review">
                  <p style={{ marginTop: 0, color: "#64748b", fontSize: "0.9rem" }}>
                    Review the extracted route, save a format template so similar layouts match
                    automatically next time (offline, no external model), and open{" "}
                    <strong>View OARC preview</strong> to check the Create-Order shaped form
                    (ops, instructions, PL, uploaded docs).
                  </p>
                  <div className="flex gap-2 flex-wrap mb-3">
                    <Button
                      type="button"
                      label="View OARC preview"
                      icon="pi pi-eye"
                      outlined
                      size="small"
                      disabled={!analyzed || !analysisPayload}
                      onClick={() => setOarcPreviewOpen(true)}
                    />
                    <Button
                      type="button"
                      label="Save GA format"
                      icon="pi pi-bookmark"
                      outlined
                      size="small"
                      loading={savingFormat === "drawing"}
                      disabled={!analyzed || !sessionId}
                      onClick={() => saveFormat("drawing")}
                    />
                    {docs.partslist && (
                      <Button
                        type="button"
                        label="Save PL format"
                        icon="pi pi-bookmark"
                        outlined
                        size="small"
                        loading={savingFormat === "partslist"}
                        disabled={!analyzed || !sessionId}
                        onClick={() => saveFormat("partslist")}
                      />
                    )}
                    {docs.wirelist && (
                      <Button
                        type="button"
                        label="Save WL format"
                        icon="pi pi-bookmark"
                        outlined
                        size="small"
                        loading={savingFormat === "wirelist"}
                        disabled={!analyzed || !sessionId}
                        onClick={() => saveFormat("wirelist")}
                      />
                    )}
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    <Button type="button" label="Save Draft" icon="pi pi-save" outlined size="small" onClick={saveDraft} disabled={!routeCardId} />
                  </div>
                </div>
              </TabPanel>
            </TabView>
          </section>
        </div>

        <div className="rca-footer">
          <Button
            type="button"
            label="View OARC preview"
            icon="pi pi-eye"
            outlined
            size="small"
            disabled={!analyzed || !analysisPayload}
            onClick={() => setOarcPreviewOpen(true)}
          />
          <Button type="button" label="Save Draft" icon="pi pi-save" outlined size="small" onClick={saveDraft} disabled={!routeCardId} />
        </div>

      <OarcPreviewDialog
        visible={oarcPreviewOpen}
        onHide={() => setOarcPreviewOpen(false)}
        docs={docs}
        payload={
          analysisPayload
            ? {
                ...analysisPayload,
                routeOperations: routeOps,
                suggestedOperations: suggestedOps,
                partsList: partsListSummary,
                bomItems,
                drawingInfo,
              }
            : null
        }
      />

      <OpTemplatePickerDialog
        visible={tplPickerOpen}
        onHide={() => setTplPickerOpen(false)}
        onSelect={addFromTemplate}
      />

      <Dialog
        header="Drawing viewer"
        visible={viewerOpen}
        onHide={() => setViewerOpen(false)}
        style={{ width: "min(92vw, 56rem)" }}
        maximizable
      >
        <div style={{ height: "70vh" }}>
          <DrawingPreview url={previewUrl} fileType={docs.drawing?.type} />
        </div>
      </Dialog>

      <Dialog
        header={
          editIsNew
            ? `Add operation (OP ${editRow?.opNo ?? ""})`
            : `Edit OP ${editRow?.opNo ?? ""}`
        }
        visible={editVisible}
        onHide={() => setEditVisible(false)}
        style={{ width: "min(92vw, 40rem)" }}
        className="rca-edit-dialog"
        footer={
          <div className="flex justify-content-end gap-2">
            <Button type="button" label="Cancel" outlined size="small" onClick={() => setEditVisible(false)} />
            <Button type="button" label="Save" icon="pi pi-check" size="small" onClick={saveEdit} />
          </div>
        }
      >
        {editRow && (
          <div className="grid formgrid p-fluid">
            {[
              ["operation", "Operation"],
              ["workCentre", "Work centre"],
              ["machine", "Machine"],
              ["tool", "Tool"],
              ["items", "Items"],
              ["torqueSpec", "Torque"],
              ["reference", "Reference"],
              ["setup", "Setup"],
              ["time", "Time"],
              ["inspection", "Inspection"],
            ].map(([key, label]) => (
              <div className="field col-12 md:col-6" key={key}>
                <label htmlFor={`rca-${key}`}>{label}</label>
                <InputText
                  id={`rca-${key}`}
                  value={editRow[key] ?? ""}
                  onChange={(e) => setEditRow((r) => ({ ...r, [key]: e.target.value }))}
                />
              </div>
            ))}
            <div className="field col-12">
              <label htmlFor="rca-instructionText">Operation instruction</label>
              <InputTextarea
                id="rca-instructionText"
                rows={4}
                value={editRow.instructionText ?? ""}
                onChange={(e) => setEditRow((r) => ({ ...r, instructionText: e.target.value }))}
              />
            </div>
          </div>
        )}
      </Dialog>
    </AppShell>
  );
}
