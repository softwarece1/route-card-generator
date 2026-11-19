import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "primereact/button";
import { Column } from "primereact/column";
import { DataTable } from "primereact/datatable";
import { Dialog } from "primereact/dialog";
import { confirmDialog } from "primereact/confirmdialog";
import SafeInputText from "@/components/SafeInputText";
import SafeInputTextarea from "@/components/SafeInputTextarea";
import { Message } from "primereact/message";
import { ProgressBar } from "primereact/progressbar";
import { TabPanel, TabView } from "primereact/tabview";
import { Tag } from "primereact/tag";
import { Dropdown } from "primereact/dropdown";
import { toast } from "@/lib/toast";
import { getVlmPageIndexes } from "@/lib/vlmPrefs";
import { isExcelFilename, triggerBlobDownload } from "@/lib/excelPreview";
import {
  addFavorite,
  analyzeSession,
  approveRouteCard,
  completeIedReview,
  cancelAnalyzeSession,
  copyJsonToClipboard,
  createSession,
  deleteSessionDocument,
  downloadJson,
  exportPmfOarc,
  fetchDrawingFileBlob,
  fetchDrawingTableCrop,
  fetchFavorites,
  fetchItemLinkReport,
  fetchMachinesQuietly,
  fetchMyExtractionDetail,
  fetchPlants,
  fetchPriorExtractions,
  fetchRecent,
  fetchReviewFlags,
  fetchSessionDocumentBlob,
  fetchWorkCenterCatalog,
  getSession,
  isCanceledError,
  learnFormatTemplate,
  recallIedReview,
  relinkSessionWorkCentres,
  resolveReviewFlag,
  saveRouteDraft,
  shareRouteToIed,
  updateRouteCard,
  uploadSessionDocument,
} from "@/services/routeCardApi";
import { getUser } from "@/lib/auth";
import { routeStatusLabel as workflowStatusLabel, routeStatusTone } from "@/lib/routeStatus";
import { Checkbox } from "primereact/checkbox";
import ExcelPreviewDialog from "@/components/ExcelPreviewDialog";
import OarcPreviewDialog from "@/components/OarcPreviewDialog";
import OpTemplatePickerDialog from "@/components/OpTemplatePickerDialog";
import RouteRemarksPanel from "@/components/RouteRemarksPanel";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import {
  insertTemplateSteps,
  mergeSelectedRouteOps,
  renumberRouteOps,
  squashConsecutiveSameWcRouteOps,
  templateStepToRouteOp,
} from "@/lib/pmfOrderPrefill";
import {
  annotateItemMentions,
  collectMentionedItemNos,
  formatItemChip,
} from "@/lib/itemLabels";
import { normalizeInstructionCase, sanitizeOperatorInstruction } from "@/lib/instructionCase";
import {
  collectTableViewHints,
  resolveDrawingIdForTableHint,
} from "@/lib/tableViewHints";
import InstructionClickEdit from "@/components/InstructionClickEdit";
import "@fontsource/rubik/400.css";
import "@fontsource/rubik/500.css";
import "@fontsource/rubik/600.css";
import "@fontsource/rubik/700.css";
import "@fontsource/rubik/800.css";
import "./route-card-generation-alt.scss";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ADMIN_PLANT_LS_KEY = "pmf.admin.generatePlant";

function readStoredAdminPlant() {
  try {
    return (localStorage.getItem(ADMIN_PLANT_LS_KEY) || "").trim();
  } catch {
    return "";
  }
}

function storeAdminPlant(code) {
  try {
    const v = (code || "").trim();
    if (v) localStorage.setItem(ADMIN_PLANT_LS_KEY, v);
  } catch {
    /* ignore */
  }
}

const UPLOAD_SLOTS = [
  {
    role: "drawing",
    title: "Drawing (GA)",
    hint: "PDF / TIFF · select several files at once (Max 10 MB each)",
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
  workCentreId: null,
  machineId: null,
  linkStatus: "manual_override",
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

function OpItemsList({ itemsUsed, fallback, itemLookup = {}, mentionedNos = null }) {
  const rows = (Array.isArray(itemsUsed) ? itemsUsed : []).filter((i) => i?.itemNo != null);
  const mentioned = mentionedNos instanceof Set ? mentionedNos : null;
  const leftover = mentioned
    ? rows.filter((i) => !mentioned.has(String(i.itemNo)) && !mentioned.has(Number(i.itemNo)))
    : rows;
  if (leftover.length === 0) {
    return fallback && rows.length === 0 ? <div className="rca-op__features">{fallback}</div> : null;
  }
  return (
    <div className="rca-op__items">
      {leftover.map((item, idx) => (
        <span key={`${item.itemNo}-${idx}`}>
          <span className="rca-op__item">
            <span className="rca-op__item-no">{formatItemChip(item, itemLookup)}</span>
          </span>
          {idx < leftover.length - 1 ? ", " : null}
        </span>
      ))}
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
  const [searchParams, setSearchParams] = useSearchParams();

  const [sessionId, setSessionId] = useState(null);
  const [docs, setDocs] = useState({ drawing: null, drawings: [], wirelist: null, partslist: null });
  const [slotErrors, setSlotErrors] = useState({});
  const [slotGlow, setSlotGlow] = useState({});
  const glowTimers = useRef({});

  const triggerSlotError = (role, message) => {
    setSlotErrors((prev) => ({ ...prev, [role]: message }));
    setSlotGlow((prev) => ({ ...prev, [role]: true }));
    if (glowTimers.current[role]) {
      clearTimeout(glowTimers.current[role]);
    }
    glowTimers.current[role] = setTimeout(() => {
      setSlotGlow((prev) => ({ ...prev, [role]: false }));
    }, 2500);
  };

  const clearSlotError = (role) => {
    setSlotErrors((prev) => ({ ...prev, [role]: null }));
    setSlotGlow((prev) => ({ ...prev, [role]: false }));
    if (glowTimers.current[role]) {
      clearTimeout(glowTimers.current[role]);
    }
  };
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
  const [drawingInfo, setDrawingInfo] = useState({});
  const [bomItems, setBomItems] = useState([]);
  const [featureCounts, setFeatureCounts] = useState([]);
  const [intelDims, setIntelDims] = useState([]);
  const [intelReqs, setIntelReqs] = useState([]);
  const [suggestedOps, setSuggestedOps] = useState([]);
  const [routeOps, setRouteOps] = useState([]);
  const [selectedRouteOps, setSelectedRouteOps] = useState([]);
  const [inspectionChars, setInspectionChars] = useState([]);
  const [revisions, setRevisions] = useState([]);
  const [partsListSummary, setPartsListSummary] = useState(null);
  const [wireListSummary, setWireListSummary] = useState(null);
  const [machines, setMachines] = useState([]);
  const [wcCatalog, setWcCatalog] = useState([]);
  const [reviewStatus, setReviewStatus] = useState("ready");
  const [editVisible, setEditVisible] = useState(false);
  const [editRow, setEditRow] = useState(null);
  const [editIsNew, setEditIsNew] = useState(false);
  const [uploadingRole, setUploadingRole] = useState(null);
  const [uploadBatch, setUploadBatch] = useState(null);
  const [instrDialog, setInstrDialog] = useState({
    visible: false,
    opKey: null,
    title: "",
    draft: "",
    itemsUsed: [],
    viewRefs: [],
  });
  const [tableCrops, setTableCrops] = useState([]); // available crops for open instruction
  const [tableCropsLoading, setTableCropsLoading] = useState(false);
  const [tableCropView, setTableCropView] = useState(null); // { label, src, filename, page }
  const [savingFormat, setSavingFormat] = useState(null);
  const [analysisPayload, setAnalysisPayload] = useState(null);
  const [oarcPreviewOpen, setOarcPreviewOpen] = useState(false);
  const [tplPickerOpen, setTplPickerOpen] = useState(false);
  const [extractedNotes, setExtractedNotes] = useState([]);
  const [mindInfo, setMindInfo] = useState(null);
  const [crossRefs, setCrossRefs] = useState([]);
  const [reviewFlags, setReviewFlags] = useState([]);
  const [itemLinkReport, setItemLinkReport] = useState(null);
  const [recentItems, setRecentItems] = useState([]);
  const [favorites, setFavorites] = useState([]);
  const [sheetDialogOpen, setSheetDialogOpen] = useState(false);
  const [openingSession, setOpeningSession] = useState(false);
  const [excelPreview, setExcelPreview] = useState(null);
  const [opComment, setOpComment] = useState("");
  const [plantDialog, setPlantDialog] = useState({
    visible: false,
    mode: "generate", // generate | relink
    draft: "",
  });
  const [priorDialog, setPriorDialog] = useState({
    visible: false,
    matches: [],
    checking: false,
  });
  const [plants, setPlants] = useState([]);
  const [plantsLoading, setPlantsLoading] = useState(false);
  const [adminPlant, setAdminPlant] = useState(() => readStoredAdminPlant());
  const analyzeAbortRef = useRef(null);
  const analyzingRef = useRef(false);
  const sessionIdRef = useRef(sessionId);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    analyzingRef.current = analyzing;
  }, [analyzing]);

  const hasGa = Boolean(docs.drawing || (docs.drawings && docs.drawings.length));
  const canAnalyze = Boolean(hasGa && docs.partslist && drawingId && !analyzing && !uploadingRole);
  const showResults = analyzed && !analyzing;

  const activeDrawing = useMemo(() => {
    const list = docs.drawings || [];
    if (!list.length) return docs.drawing || null;
    return (
      list.find((d) => d.drawingId === drawingId || d.id === drawingId) ||
      list[list.length - 1] ||
      null
    );
  }, [docs.drawing, docs.drawings, drawingId]);

  const applyPayload = useCallback((payload) => {
    if (!payload) return;
    setAnalysisPayload(payload);
    setRouteCardId(payload.id ?? null);
    if (payload.drawing?.id) setDrawingId(payload.drawing.id);
    if (payload.sessionId) {
      sessionIdRef.current = payload.sessionId;
      setSessionId(payload.sessionId);
    }
    setDrawingInfo(payload.drawingInfo || {});
    setBomItems(payload.bomItems || []);
    setFeatureCounts(payload.featureCounts || []);
    setIntelDims(payload.intelligenceDimensions || []);
    setIntelReqs(payload.intelligenceRequirements || []);
    setSuggestedOps(payload.suggestedOperations || []);
    setRouteOps(payload.routeOperations || []);
    setSelectedRouteOps([]);
    setInspectionChars(payload.inspectionChars || []);
    setRevisions(payload.revisions || []);
    setWireListSummary(payload.wireList || null);
    setPartsListSummary(payload.partsList || null);
    setExtractedNotes(payload.notes || []);
    setMindInfo({
      ...(payload.mind || {}),
      warnings: [],
      viewRefs: payload.viewRefs || payload.mind?.viewRefs || [],
    });
    setCrossRefs(payload.crossRefs || payload.mind?.crossRefs || []);
    const st = (payload.status || "").toLowerCase();
    if (st === "approved") setReviewStatus("approved");
    else if (st === "ied_review") setReviewStatus("ied_review");
    else if (st === "ied_complete") setReviewStatus("ied_complete");
    else if (st === "draft") setReviewStatus("draft");
    else setReviewStatus("ready");
    if (payload.reviewFlags) setReviewFlags(payload.reviewFlags);
    if (payload.itemLinkReport) setItemLinkReport(payload.itemLinkReport);
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

  // Leaving the page / unmount: abort HTTP + tell backend to stop Ollama
  useEffect(() => {
    return () => {
      analyzeAbortRef.current?.abort();
      analyzeAbortRef.current = null;
      const sid = sessionIdRef.current;
      if (sid && analyzingRef.current) {
        cancelAnalyzeSession(sid);
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const plant =
      (getUser()?.role === "admin" && (adminPlant || "").trim()) || undefined;
    Promise.all([
      fetchMachinesQuietly(),
      fetchWorkCenterCatalog(undefined, { plant }),
    ]).then(([m, wc]) => {
      if (!cancelled) {
        setMachines(m || []);
        setWcCatalog(wc || []);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [adminPlant]);

  const ensurePlantsLoaded = useCallback(async () => {
    if (plants.length) return plants;
    setPlantsLoading(true);
    try {
      const rows = await fetchPlants({ activeOnly: true });
      const list = Array.isArray(rows) ? rows : [];
      setPlants(list);
      return list;
    } catch (e) {
      toast.error(e.message || "Could not load plants");
      setPlants([]);
      return [];
    } finally {
      setPlantsLoading(false);
    }
  }, [plants.length]);

  const openAdminPlantDialog = useCallback(
    async (mode = "generate") => {
      const list = await ensurePlantsLoaded();
      const preferred =
        (adminPlant || "").trim() ||
        readStoredAdminPlant() ||
        (list[0]?.code || "");
      setPlantDialog({ visible: true, mode, draft: preferred });
    },
    [adminPlant, ensurePlantsLoaded],
  );

  const wcDropdownOptions = useMemo(
    () =>
      (wcCatalog || []).map((w) => ({
        label: w.code && w.name && w.code !== w.name ? `${w.code} · ${w.name}` : w.code || w.name,
        value: Number(w.id),
        raw: w,
      })),
    [wcCatalog]
  );

  const machineOptionsForEdit = useMemo(() => {
    const wcId = editRow?.workCentreId;
    const wc = (wcCatalog || []).find((w) => w.id === wcId);
    const list = wc?.machines || [];
    return list.map((m) => ({
      label: m.isManualPlaceholder ? `${m.name} (manpower)` : m.name,
      value: m.id,
      raw: m,
    }));
  }, [wcCatalog, editRow?.workCentreId]);

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
    // Ref, not state: a multi-file batch must reuse the session created by the first file.
    if (sessionIdRef.current) return sessionIdRef.current;
    const s = await createSession();
    sessionIdRef.current = s.id;
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

  const selectDrawingPreview = async (drawing, { openViewer = false } = {}) => {
    if (!drawing?.drawingId) return;
    setDrawingId(drawing.drawingId);
    setDocs((prev) => ({ ...prev, drawing }));
    await loadPreview(drawing.drawingId, drawing.type);
    if (openViewer) setViewerOpen(true);
  };

  const openSlotDocument = async (role, file, { downloadOnly = false } = {}) => {
    if (!sessionId || !file) return;
    try {
      const blob = await fetchSessionDocumentBlob(sessionId, role, file.id || null);
      const name = file.name || `${role}.xlsx`;
      if (downloadOnly) {
        triggerBlobDownload(blob, name);
        toast.success(`Downloaded ${name}`);
        return;
      }
      if (isExcelFilename(name) || isExcelFilename(file.type)) {
        setExcelPreview({ blob, name });
        return;
      }
      // PDF / other — open in a new tab
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(e.message || "Could not open file");
    }
  };

  const isDuplicateDrawingName = (fileName, drawings = docs.drawings) => {
    const key = String(fileName || "").trim().toLowerCase();
    if (!key) return false;
    return (drawings || []).some((d) => String(d.name || "").trim().toLowerCase() === key);
  };

  /** Clear UI only — session is created lazily on next upload. */
  const resetPage = () => {
    if (analyzingRef.current) {
      stopAnalysis({ silent: true });
    }
    clearPreview();
    setDocs({ drawing: null, drawings: [], wirelist: null, partslist: null });
    setDrawingId(null);
    setRouteCardId(null);
    sessionIdRef.current = null;
    setSessionId(null);
    setZoom(1);
    setAnalyzing(false);
    setAnalyzed(false);
    setTaskProgress({});
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

  const applySlotFile = async (role, file, options = {}) => {
    const { quiet = false, manageBusy = true, preview = true } = options;
    if (!file) return "skip";
    clearSlotError(role);
    const slot = UPLOAD_SLOTS.find((s) => s.role === role);
    const slotTitle = slot?.title || role;
    if (role === "drawing" && isDuplicateDrawingName(file.name)) {
      triggerSlotError(role, `Duplicate file: “${file.name}” is already uploaded. Please choose a different file.`);
      toast.warn(`${slotTitle}: “${file.name}” is already uploaded. Choose a different file.`);
      return "skip";
    }
    const ext = `.${(file.name.split(".").pop() || "").toLowerCase()}`;
    const allowed = (slot?.accept || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    if (allowed.length && !allowed.includes(ext)) {
      const allowedText = role === "drawing" ? "a PDF or TIFF file (.pdf, .tif, .tiff)" : "a PDF or Excel file (.pdf, .xls, .xlsx)";
      const errorMsg = `Invalid file format (${ext || "unknown"}). Please upload ${allowedText}.`;
      triggerSlotError(role, errorMsg);
      toast.error(
        `${slotTitle}: “${file.name}” is not an allowed type (${ext || "unknown"}). ` +
          `Please upload: ${allowed.join(", ")}.`
      );
      return "skip";
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      const errorMsg = "File exceeds the 10 MB maximum upload limit.";
      triggerSlotError(role, errorMsg);
      toast.error(`${slotTitle}: file exceeds 10 MB limit`);
      return "skip";
    }
    if (manageBusy) setUploadingRole(role);
    if (!quiet) toast.info(`Uploading ${slotTitle}…`);
    try {
      const sid = await ensureSession();
      const meta = await uploadSessionDocument(sid, role, file);
      clearSlotError(role);
      syncDocsFromSession(meta.documents || [], meta.drawingIds || (meta.drawingId ? [meta.drawingId] : []));
      const fileType = meta.document?.file_type || file.name.split(".").pop()?.toUpperCase();
      if (meta.drawingId) {
        setDrawingId(meta.drawingId);
        if (role === "drawing" && preview) {
          await loadPreview(meta.drawingId, fileType);
        }
      }
      setAnalyzed(false);
      setAnalyzing(false);
      setTaskProgress({});
      setResultTab(0);
      setReviewStatus("ready");
      setRouteOps([]);
      setRouteCardId(null);
      if (!quiet) toast.success(`${slotTitle} uploaded.`);
      const uploadWarns = [
        ...(meta.warnings || []),
        ...(meta.document?.warnings || []),
      ].filter(Boolean);
      for (const w of [...new Set(uploadWarns)]) {
        toast.warn(w);
      }
      return { status: "ok", drawingId: meta.drawingId || null, fileType };
    } catch (error) {
      const detail = error?.response?.data?.detail;
      const errMsg = typeof detail === "string" ? detail : error.message || "Upload failed";
      triggerSlotError(role, errMsg);
      toast.error(errMsg);
      return "fail";
    } finally {
      if (manageBusy) setUploadingRole(null);
    }
  };

  const applySlotFiles = async (role, fileList) => {
    const incoming = Array.from(fileList || []).filter(Boolean);
    if (!incoming.length) return;
    if (role !== "drawing") {
      await applySlotFile(role, incoming[0]);
      return;
    }

    const seen = new Set();
    const files = [];
    for (const f of incoming) {
      const key = String(f.name || "").trim().toLowerCase();
      if (!key) continue;
      if (seen.has(key) || isDuplicateDrawingName(f.name)) {
        toast.warn(`Skipped duplicate drawing: ${f.name}`);
        continue;
      }
      seen.add(key);
      files.push(f);
    }
    if (!files.length) return;
    if (files.length === 1) {
      await applySlotFile(role, files[0]);
      return;
    }

    setUploadingRole(role);
    let ok = 0;
    let lastPreview = null;
    try {
      for (let i = 0; i < files.length; i += 1) {
        const file = files[i];
        setUploadBatch({ role, current: i + 1, total: files.length, name: file.name });
        // Sequential so each GA lands on the same session before the next starts.
        // eslint-disable-next-line no-await-in-loop
        const result = await applySlotFile(role, file, { quiet: true, manageBusy: false, preview: false });
        if (result?.status === "ok") {
          ok += 1;
          if (result.drawingId) lastPreview = result;
        }
      }
      if (lastPreview?.drawingId) {
        await loadPreview(lastPreview.drawingId, lastPreview.fileType);
      }
    } finally {
      setUploadingRole(null);
      setUploadBatch(null);
    }
    if (ok > 0) {
      toast.success(
        ok === files.length
          ? `Uploaded ${ok} GA drawings.`
          : `Uploaded ${ok} of ${files.length} GA drawings.`
      );
    }
  };

  const removeSlot = async (role, documentId = null) => {
    clearSlotError(role);
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
    setAnalysisPayload(null);
    setResultTab(0);
  };

  const stopAnalysis = useCallback(async ({ silent = false } = {}) => {
    analyzeAbortRef.current?.abort();
    analyzeAbortRef.current = null;
    const sid = sessionIdRef.current;
    if (sid) {
      await cancelAnalyzeSession(sid);
    }
    setAnalyzing(false);
    setTaskProgress({});
    if (!silent) toast.info("Analysis stopped.");
  }, []);

  const runAnalysis = async (plantCode) => {
    if (!sessionId || !hasGa || analyzing) return;
    const plant = (plantCode || "").trim() || undefined;
    if (getUser()?.role === "admin" && !plant) {
      toast.warn("Select a plant before generating.");
      return;
    }
    analyzeAbortRef.current?.abort();
    const ac = new AbortController();
    analyzeAbortRef.current = ac;
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
      const vlmPrefs = getVlmPageIndexes();
      const payload = await analyzeSession(sessionId, {
        signal: ac.signal,
        vlmPageIndexes: vlmPrefs.length ? vlmPrefs : undefined,
        plant,
      });
      if (ac.signal.aborted) return;
      if (plant) {
        setAdminPlant(plant);
        storeAdminPlant(plant);
      }
      applyPayload(payload);
      setAnalyzing(false);
      setAnalyzed(true);
      setResultTab(1);
      toast.success("OARC generated. Review the results in the tabs below.");
    } catch (error) {
      setAnalyzing(false);
      if (isCanceledError(error) || ac.signal.aborted) {
        return;
      }
      toast.error(error.message || "Analysis failed");
    } finally {
      if (analyzeAbortRef.current === ac) {
        analyzeAbortRef.current = null;
      }
    }
  };

  const proceedGenerate = () => {
    if (getUser()?.role === "admin") {
      openAdminPlantDialog("generate");
      return;
    }
    runAnalysis();
  };

  const requestGenerate = async () => {
    if (!canAnalyze || !sessionId) return;
    setPriorDialog((s) => ({ ...s, checking: true }));
    try {
      const prior = await fetchPriorExtractions(sessionId);
      const matches = prior?.matches || [];
      if (matches.length) {
        setPriorDialog({ visible: true, matches, checking: false });
        return;
      }
    } catch {
      /* offline / API miss — continue with generate */
    } finally {
      setPriorDialog((s) => ({ ...s, checking: false }));
    }
    proceedGenerate();
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

  const sessionDrawingsForCrop = useMemo(() => {
    const fromDocs = (docs.drawings || []).map((d) => ({
      id: d.drawingId || d.id,
      filename: d.name || d.filename || "",
      name: d.name || d.filename || "",
    }));
    // Prefer real RcDrawing ids when present on analysis payload
    const fromPayload = (analysisPayload?.documents || [])
      .filter((d) => d.role === "drawing" && d.drawingId)
      .map((d) => ({
        id: d.drawingId,
        filename: d.filename || "",
        name: d.filename || "",
      }));
    const byId = new Map();
    for (const row of [...fromPayload, ...fromDocs]) {
      if (row.id) byId.set(Number(row.id), row);
    }
    if (drawingId) {
      byId.set(Number(drawingId), {
        id: Number(drawingId),
        filename: docs.drawing?.name || "",
        name: docs.drawing?.name || "",
      });
    }
    return [...byId.values()];
  }, [docs.drawings, docs.drawing, analysisPayload, drawingId]);

  const loadTableCropsForInstruction = useCallback(
    async (draft, viewRefs = []) => {
      const mergedRefs = [
        ...(viewRefs || []),
        ...((mindInfo && mindInfo.viewRefs) || []),
      ];
      const hints = collectTableViewHints(draft, mergedRefs);
      if (!hints.length) {
        setTableCrops([]);
        return;
      }
      setTableCropsLoading(true);
      try {
        const results = [];
        for (const hint of hints) {
          const did = resolveDrawingIdForTableHint(hint, sessionDrawingsForCrop);
          if (!did) continue;
          try {
            let crop = await fetchDrawingTableCrop(did, {
              table: hint.tableId,
              page: hint.sheet || undefined,
            });
            // Single-page sheet PDFs often use sheet no in the filename only
            if (!crop?.available && hint.sheet) {
              crop = await fetchDrawingTableCrop(did, { table: hint.tableId });
            }
            if (crop?.available && crop.imageBase64) {
              results.push({
                ...crop,
                src: `data:${crop.mime || "image/jpeg"};base64,${crop.imageBase64}`,
              });
            }
          } catch {
            /* gated — skip unavailable */
          }
        }
        setTableCrops(results);
      } finally {
        setTableCropsLoading(false);
      }
    },
    [mindInfo, sessionDrawingsForCrop],
  );

  const openSuggestedInstruction = (op) => {
    const key = String(op.id || op.opNo);
    const draft = normalizeInstructionCase(
      sanitizeOperatorInstruction(op.instructionText || op.reason || "") ||
        op.instructionText ||
        op.reason ||
        ""
    );
    const viewRefs = op.viewRefs || [];
    setTableCrops([]);
    setTableCropView(null);
    setInstrDialog({
      visible: true,
      opKey: key,
      title: `OP ${op.opNo} — ${op.operation || "Operation"}`,
      draft,
      itemsUsed: op.itemsUsed || [],
      viewRefs,
    });
    loadTableCropsForInstruction(draft, viewRefs);
  };

  const saveSuggestedInstruction = async () => {
    const key = instrDialog.opKey;
    const draft = instrDialog.draft ?? "";
    if (!key) {
      setInstrDialog({
        visible: false,
        opKey: null,
        title: "",
        draft: "",
        itemsUsed: [],
        viewRefs: [],
      });
      setTableCrops([]);
      return;
    }
    setSuggestedOps((prev) =>
      (prev || []).map((op) =>
        String(op.id || op.opNo) === key ? { ...op, instructionText: draft, reason: draft } : op
      )
    );
    const nextRoute = (routeOps || []).map((op) =>
      String(op.id || op.opNo) === key ? { ...op, instructionText: draft, reason: draft } : op
    );
    setInstrDialog({
      visible: false,
      opKey: null,
      title: "",
      draft: "",
      itemsUsed: [],
      viewRefs: [],
    });
    setTableCrops([]);
    setTableCropView(null);
    if (routeCardId && nextRoute.some((op) => String(op.id || op.opNo) === key)) {
      await persistOps(nextRoute);
    } else {
      setRouteOps(nextRoute);
    }
    toast.success("Instruction saved.");
  };

  const saveEdit = async () => {
    if (!editRow?.operation) {
      toast.warn("Operation name is required.");
      return;
    }
    const nextRow = {
      ...editRow,
      linkStatus: "manual_override",
      type: editRow.workCentreName || editRow.workCentre || editRow.type,
    };
    const exists = !editIsNew && routeOps.some((r) => String(r.id) === String(editRow.id));
    const rows = exists
      ? routeOps.map((r) => (String(r.id) === String(editRow.id) ? nextRow : r))
      : [...routeOps, nextRow].sort((a, b) => Number(a.opNo) - Number(b.opNo));
    setEditVisible(false);
    setEditIsNew(false);
    await persistOps(rows);
    toast.success(exists ? "Route operation updated." : "Route operation added.");
  };

  const removeOp = async (row) => {
    await persistOps(routeOps.filter((r) => String(r.id) !== String(row.id)));
    toast.info(`Removed OP ${row.opNo}.`);
  };

  const relinkWorkCentres = async (plantCode) => {
    const sid = sessionIdRef.current || sessionId;
    if (!sid) {
      toast.warn("Open or analyze a session first.");
      return;
    }
    if (!routeOps?.length) {
      toast.warn("No route operations to re-link.");
      return;
    }
    const fromArg = typeof plantCode === "string" ? plantCode : "";
    const plant = (fromArg || adminPlant || "").trim() || undefined;
    if (getUser()?.role === "admin" && !plant) {
      openAdminPlantDialog("relink");
      return;
    }
    try {
      const payload = await relinkSessionWorkCentres(sid, { plant });
      if (plant) {
        setAdminPlant(plant);
        storeAdminPlant(plant);
      }
      applyPayload(payload);
      const c = payload?.relink?.counts || {};
      const linked = c.linked ?? 0;
      const unresolved = c.unresolved ?? 0;
      const kept = c.skippedOverrides ?? 0;
      toast.success(
        `Re-linked work centres — linked ${linked} · unresolved ${unresolved} · kept overrides ${kept}`,
      );
    } catch (error) {
      toast.error(error.message || "Re-link failed");
    }
  };

  const confirmAdminPlant = () => {
    const code = (plantDialog.draft || "").trim();
    if (!code) {
      toast.warn("Select a plant.");
      return;
    }
    const mode = plantDialog.mode;
    setPlantDialog((s) => ({ ...s, visible: false }));
    setAdminPlant(code);
    storeAdminPlant(code);
    if (mode === "relink") {
      relinkWorkCentres(code);
    } else {
      runAnalysis(code);
    }
  };

  const sameWcMergePreview = useMemo(
    () => squashConsecutiveSameWcRouteOps(routeOps),
    [routeOps],
  );
  const canMergeSameWc =
    sameWcMergePreview.beforeCount > sameWcMergePreview.afterCount &&
    sameWcMergePreview.mergedGroups > 0;

  const mergeSameWcOps = () => {
    const preview = squashConsecutiveSameWcRouteOps(routeOps);
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
      accept: async () => {
        setSelectedRouteOps([]);
        await persistOps(preview.rows);
        toast.success(
          `Merged to ${preview.afterCount} operation(s) (${preview.mergedGroups} WC group(s)).`,
        );
      },
    });
  };

  const mergeSelectedOps = () => {
    const result = mergeSelectedRouteOps(routeOps, selectedRouteOps);
    if (!result.ok) {
      toast.warn(result.error || "Cannot merge selection.");
      return;
    }
    confirmDialog({
      header: "Merge selected",
      message: `Merge ${result.mergedCount} selected operations into one? Instructions and items are combined; work centre is taken from the first selected op.`,
      icon: "pi pi-compress",
      className: "p-confirm-dialog-sm",
      acceptLabel: "Merge",
      rejectLabel: "Cancel",
      acceptClassName: "p-button-sm",
      rejectClassName: "p-button-sm p-button-outlined",
      accept: async () => {
        setSelectedRouteOps([]);
        await persistOps(result.rows);
        toast.success(`Merged ${result.mergedCount} operations into one.`);
      },
    });
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

  const unresolvedBlocking = (reviewFlags || []).filter(
    (f) => !f.resolved && ["high", "medium"].includes((f.severity || "").toLowerCase()),
  );
  const currentUser = getUser();
  const userRole = currentUser?.role;
  const isIedUser = userRole === "ied";
  const isAdminUser = userRole === "admin";
  const isDeptHeadUser = userRole === "dept_head";
  const canShareToIed =
    Boolean(routeCardId) &&
    (reviewStatus === "draft" || reviewStatus === "ied_complete") &&
    !isIedUser;
  const canCompleteIed =
    Boolean(routeCardId) &&
    reviewStatus === "ied_review" &&
    (isIedUser || isAdminUser);
  const canRecallIed =
    Boolean(routeCardId) &&
    reviewStatus === "ied_review" &&
    (isAdminUser || isDeptHeadUser || !isIedUser);
  const canApprove =
    Boolean(routeCardId) &&
    reviewStatus === "ied_complete" &&
    userRole !== "ied" &&
    (unresolvedBlocking.length === 0 || isAdminUser);
  const canAdminOverrideApprove =
    isAdminUser &&
    Boolean(routeCardId) &&
    reviewStatus !== "approved" &&
    (reviewStatus !== "ied_complete" || unresolvedBlocking.length > 0);
  const opsReadOnly =
    reviewStatus === "approved" ||
    (reviewStatus === "ied_review" && !isIedUser && !isAdminUser) ||
    (isIedUser && reviewStatus !== "ied_review");
  const iedFieldsOnly = reviewStatus === "ied_review" && isIedUser;

  const shareToIed = async () => {
    if (!routeCardId) return;
    try {
      const wasAlready = reviewStatus === "ied_review";
      const payload = await shareRouteToIed(routeCardId);
      applyPayload(payload);
      toast.success(
        wasAlready
          ? "Already awaiting IED review."
          : "Shared to IED — awaiting review.",
      );
    } catch (error) {
      toast.error(error.message || "Share to IED failed");
    }
  };

  const completeIed = async () => {
    if (!routeCardId) return;
    try {
      const payload = await completeIedReview(routeCardId);
      applyPayload(payload);
      toast.success("IED review complete — awaiting eng / dept-head approval.");
    } catch (error) {
      toast.error(error.message || "Complete IED failed");
    }
  };

  const recallIed = async () => {
    if (!routeCardId) return;
    try {
      const payload = await recallIedReview(routeCardId);
      applyPayload(payload);
      toast.success("Recalled from IED review.");
    } catch (error) {
      toast.error(error.message || "Recall failed");
    }
  };

  const approveCard = async (override = false) => {
    if (!routeCardId) return;
    try {
      const payload = await approveRouteCard(routeCardId, { adminOverride: override });
      applyPayload(payload);
      setReviewStatus("approved");
      toast.success("Route card approved.");
    } catch (error) {
      toast.error(error.message || "Approve failed");
    }
  };

  const reviewStatusLabel = workflowStatusLabel(
    reviewStatus === "ready" ? "" : reviewStatus,
  );
  const reviewTagSeverity =
    routeStatusTone(reviewStatus) === "success"
      ? "success"
      : routeStatusTone(reviewStatus) === "info"
        ? "info"
        : routeStatusTone(reviewStatus) === "warn"
          ? "warning"
          : "secondary";

  const downloadCreateOrder = async () => {
    if (!routeCardId) return;
    try {
      const data = await exportPmfOarc(routeCardId);
      downloadJson(`pmf-oarc-${routeCardId}.json`, data);
      toast.success("Downloaded Create Order JSON");
    } catch (e) {
      toast.error(e.message || "Export failed");
    }
  };

  const copyCreateOrder = async () => {
    if (!routeCardId) return;
    try {
      const data = await exportPmfOarc(routeCardId);
      await copyJsonToClipboard(data);
      toast.success("Copied Create Order JSON");
    } catch (e) {
      toast.error(e.message || "Copy failed");
    }
  };

  const toggleFlag = async (flag, resolved) => {
    try {
      await resolveReviewFlag(flag.id, resolved);
      setReviewFlags((prev) =>
        prev.map((f) => (f.id === flag.id ? { ...f, resolved } : f)),
      );
    } catch (e) {
      toast.error(e.message || "Could not update flag");
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const [r, f] = await Promise.all([fetchRecent(), fetchFavorites()]);
        setRecentItems(r.items || []);
        setFavorites(f.items || []);
      } catch {
        /* ignore */
      }
    })();
  }, []);

  const openSessionById = useCallback(
    async (sid, { fromUrl = false } = {}) => {
      const id = Number(sid);
      if (!id || Number.isNaN(id) || openingSession) return;
      if (sessionId === id && analyzed) return;
      setOpeningSession(true);
      const loadingId = toast.loading(`Opening session ${id}…`);
      try {
        if (analyzingRef.current) {
          await stopAnalysis({ silent: true });
        }
        const [sess, detail] = await Promise.all([
          getSession(id),
          fetchMyExtractionDetail(id),
        ]);
        sessionIdRef.current = id;
        setSessionId(id);
        syncDocsFromSession(
          sess.documents || [],
          sess.drawingIds || (sess.drawingId ? [sess.drawingId] : []),
        );
        if (detail?.payload) {
          applyPayload({ ...detail.payload, sessionId: id });
          setAnalyzed(true);
          setResultTab(1);
        } else {
          setAnalyzed(false);
          setAnalysisPayload(null);
          setRouteOps([]);
          setExtractedNotes([]);
        }
        const drawings = (sess.documents || []).filter((d) => d.role === "drawing");
        const last = drawings[drawings.length - 1];
        if (last?.drawingId) {
          await loadPreview(last.drawingId, last.file_type || last.fileType);
        }
        if (!fromUrl) {
          setSearchParams({ sessionId: String(id) }, { replace: true });
        }
        toast.success(`Opened ${detail?.partNumber || `session ${id}`}`);
      } catch (e) {
        toast.error(e.message || "Could not open session");
      } finally {
        toast.dismiss(loadingId);
        setOpeningSession(false);
      }
    },
    [analyzed, applyPayload, openingSession, sessionId, setSearchParams, stopAnalysis],
  );

  // Deep-link: /generator?sessionId=290
  useEffect(() => {
    const q = searchParams.get("sessionId");
    if (q && Number(q) !== sessionId) {
      openSessionById(q, { fromUrl: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when URL sessionId changes
  }, [searchParams]);

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
    ["File", activeDrawing?.name],
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

  const drawingTabs =
    (docs.drawings?.length || 0) > 1 ? (
      <div className="rca-viewer__tabs" role="tablist" aria-label="Uploaded drawings">
        {docs.drawings.map((g, i) => {
          const selected = g.drawingId === drawingId || (activeDrawing && g.id === activeDrawing.id);
          return (
            <button
              key={g.id || `${g.name}-${i}`}
              type="button"
              role="tab"
              aria-selected={selected}
              className={`rca-viewer__tab${selected ? " rca-viewer__tab--active" : ""}`}
              title={g.name}
              disabled={uploadingRole === "drawing"}
              onClick={() => selectDrawingPreview(g)}
            >
              <span className="rca-viewer__tab-label">{g.name || `GA ${i + 1}`}</span>
            </button>
          );
        })}
      </div>
    ) : null;

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
            const files = Array.from(e.target.files || []);
            e.target.value = "";
            if (files.length && !uploadingRole) applySlotFiles(slot.role, files);
          }}
        />
      ))}

        <div className="rca-content">
          {(recentItems?.length > 0 || favorites?.length > 0) && (
            <div className="rca-session-chips flex gap-2 flex-wrap mb-2 align-items-center">
              <span className="rca-session-chips__hint">Recent / favorites — click to reopen:</span>
              {recentItems.slice(0, 5).map((r) => (
                <Button
                  key={`r-${r.sessionId}`}
                  type="button"
                  size="small"
                  outlined={sessionId !== r.sessionId}
                  severity={sessionId === r.sessionId ? undefined : "secondary"}
                  disabled={openingSession}
                  label={r.partNumber || `Session ${r.sessionId}`}
                  onClick={() => openSessionById(r.sessionId)}
                  title={`Open session ${r.sessionId} in Generator`}
                />
              ))}
              {favorites.slice(0, 5).map((f) => (
                <Button
                  key={`f-${f.id}`}
                  type="button"
                  size="small"
                  outlined={sessionId !== f.sessionId}
                  severity={sessionId === f.sessionId ? undefined : "secondary"}
                  disabled={openingSession || !f.sessionId}
                  icon="pi pi-star"
                  label={f.label || f.partNumber || `Fav ${f.id}`}
                  onClick={() => f.sessionId && openSessionById(f.sessionId)}
                  title={f.sessionId ? `Open favorite session ${f.sessionId}` : "No session linked"}
                />
              ))}
            </div>
          )}
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
                {analyzing ? (
                  <Button
                    type="button"
                    label="Stop"
                    icon="pi pi-stop"
                    size="small"
                    severity="danger"
                    outlined
                    onClick={() => stopAnalysis()}
                  />
                ) : null}
                <Button
                  type="button"
                  label={
                    analyzing
                      ? "Generating…"
                      : priorDialog.checking
                        ? "Checking…"
                        : "Generate OARC"
                  }
                  icon="pi pi-bolt"
                  size="small"
                  loading={analyzing || priorDialog.checking}
                  disabled={!canAnalyze || priorDialog.checking}
                  onClick={requestGenerate}
                />
              </>
            }
          />
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
                    className={`rca-slot${active ? " rca-slot--active" : ""}${filled ? " rca-slot--filled" : ""}${uploading ? " rca-slot--uploading" : ""}${slotErrors[slot.role] ? " rca-slot--error" : ""}${slotGlow[slot.role] ? " rca-slot--glow" : ""}`}
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
                                label={multi ? "Browse files" : "Browse file"}
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
                          {drawings.map((g) => {
                            const selected =
                              g.drawingId === drawingId || (activeDrawing && g.id === activeDrawing.id);
                            return (
                              <div
                                className={`rca-slot__file${selected ? " rca-slot__file--selected" : ""}`}
                                key={g.id || g.name}
                                role="button"
                                tabIndex={0}
                                onClick={() => selectDrawingPreview(g)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter" || e.key === " ") {
                                    e.preventDefault();
                                    selectDrawingPreview(g);
                                  }
                                }}
                              >
                                <i className="pi pi-file-pdf rca-slot__file-icon" aria-hidden="true" />
                                <div className="rca-slot__file-meta">
                                  <strong title={g.name}>{g.name}</strong>
                                  <span>{g.sizeLabel}</span>
                                </div>
                                <div className="rca-slot__actions" onClick={(e) => e.stopPropagation()}>
                                  <Button
                                    type="button"
                                    icon="pi pi-eye"
                                    rounded
                                    text
                                    size="small"
                                    disabled={uploading || !g.drawingId}
                                    aria-label="View drawing"
                                    onClick={() => selectDrawingPreview(g, { openViewer: true })}
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
                            );
                          })}
                          <Button
                            type="button"
                            label="Add GAs"
                            icon="pi pi-plus"
                            outlined
                            size="small"
                            className="mt-2"
                            disabled={uploading}
                            title="Select one or more GA files"
                            onClick={() => fileInputRefs.current[slot.role]?.click()}
                          />
                        </div>
                      ) : (
                        <div className="rca-slot__file">
                          <i
                            className={`pi ${
                              isExcelFilename(file.name) ? "pi-file-excel" : "pi-file-pdf"
                            } rca-slot__file-icon`}
                            aria-hidden="true"
                          />
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
                              icon="pi pi-eye"
                              rounded
                              text
                              size="small"
                              disabled={uploading || !sessionId}
                              aria-label={`View ${slot.role}`}
                              title="View"
                              onClick={() => openSlotDocument(slot.role, file)}
                            />
                            <Button
                              type="button"
                              icon="pi pi-download"
                              rounded
                              text
                              size="small"
                              disabled={uploading || !sessionId}
                              aria-label={`Download ${slot.role}`}
                              title="Download"
                              onClick={() => openSlotDocument(slot.role, file, { downloadOnly: true })}
                            />
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
                          <span>
                            {uploadBatch?.role === slot.role && uploadBatch.total > 1
                              ? `Uploading ${uploadBatch.current} of ${uploadBatch.total}`
                              : "Uploading…"}
                          </span>
                          <span className="rca-slot__upload-hint">
                            {uploadBatch?.role === slot.role
                              ? uploadBatch.name
                              : "Please wait while the file is uploaded"}
                          </span>
                        </div>
                      ) : null}
                    </div>
                    {slotErrors[slot.role] ? (
                      <div className="rca-slot__error-msg" role="alert">
                        <i className="pi pi-exclamation-circle" aria-hidden="true" />
                        <span>{slotErrors[slot.role]}</span>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
            {uploadingRole ? (
              <Message
                className="mt-3 w-full"
                severity="info"
                text={
                  uploadBatch?.total > 1
                    ? `Uploading GA ${uploadBatch.current} of ${uploadBatch.total}: ${uploadBatch.name}`
                    : `Uploading ${UPLOAD_SLOTS.find((s) => s.role === uploadingRole)?.title || "file"}… Please wait.`
                }
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
                {drawingTabs}
                <div className="rca-viewer__canvas" style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}>
                  <DrawingPreview url={previewUrl} fileType={activeDrawing?.type} />
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
                              <h4 className="mb-2">Drawing notes (verbatim)</h4>
                              {extractedNotes.map((n, idx) => (
                                <div className="rca-note" key={`${n.stepNo}-${idx}`}>
                                  <div className="rca-note__head">
                                    <strong>Step {n.stepNo}</strong>
                                    {n.needsReview ? (
                                      <Tag value="Needs review" severity="warning" />
                                    ) : null}
                                    {n.insight ? (
                                      <Tag value="Insight" severity="info" />
                                    ) : null}
                                    {n.sourceFilename ? (
                                      <Tag value={n.sourceFilename} severity="secondary" />
                                    ) : null}
                                  </div>
                                  <p className="rca-note__text">
                                    {annotateItemMentions(n.text || "—", plItemLookup)}
                                  </p>
                                  {n.elaboratedText && n.elaboratedText !== n.text ? (
                                    <p className="rca-note__source">
                                      Elaborated: {annotateItemMentions(n.elaboratedText, plItemLookup)}
                                    </p>
                                  ) : null}
                                  {n.insight ? (
                                    <p className="rca-note__source">Insight: {n.insight}</p>
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
                        rowsPerPageOptions={[10, 25, 50, 100]}
                        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
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
                        <p style={{ margin: 0, color: "var(--pmf-text-muted)", fontSize: "0.85rem" }}>No dimension intelligence extracted.</p>
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
                        <p style={{ margin: 0, color: "var(--pmf-text-muted)", fontSize: "0.85rem" }}>No special requirements listed.</p>
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
                        {(suggestedOps || []).map((op) => {
                          const rawInstr = op.instructionText || op.reason || "";
                          const annotated = annotateItemMentions(rawInstr, plItemLookup);
                          const preview = annotated
                            ? annotated.length > 120
                              ? `${annotated.slice(0, 117)}…`
                              : annotated
                            : "—";
                          const mentioned = collectMentionedItemNos(rawInstr);
                          return (
                          <article className="rca-op" key={op.id || op.opNo}>
                            <div className="rca-op__top">
                              <div className="rca-op__no">OP {op.opNo}</div>
                              <Tag
                                value={op.type || op.workCentre || "Operation"}
                                severity={workCentreSeverity(op.type || op.workCentre)}
                              />
                            </div>
                            <h4>{op.operation}</h4>
                            <div className="rca-op__instr-row">
                              {op.elaborated ? (
                                <Tag value="Elaborated" severity="success" className="mr-1" />
                              ) : null}
                              <p className="rca-op__instr" title={annotated || undefined}>
                                {preview}
                              </p>
                              <Button
                                type="button"
                                icon={rawInstr.trim() ? "pi pi-file-edit" : "pi pi-align-left"}
                                className={`rca-op__instr-btn${rawInstr.trim() ? " rca-op__instr-btn--filled" : ""}`}
                                rounded
                                text
                                size="small"
                                aria-label={rawInstr.trim() ? "Edit instruction" : "Add instruction"}
                                tooltip={rawInstr.trim() ? "Edit instruction" : "Add instruction"}
                                tooltipOptions={{ position: "top" }}
                                onClick={() => openSuggestedInstruction(op)}
                              />
                            </div>
                            <OpItemsList
                              itemsUsed={op.itemsUsed}
                              fallback={op.items}
                              itemLookup={plItemLookup}
                              mentionedNos={mentioned}
                            />
                            <dl className="rca-op__meta">
                              {op.workCentre ? (
                                <div>
                                  <dt>Work centre</dt>
                                  <dd>{op.workCentreName ? `${op.workCentre} (${op.workCentreName})` : op.workCentre}</dd>
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
                          );
                        })}
                      </div>
                      {(wcCatalog?.length > 0 || machines?.length > 0) && (
                        <div className="mt-3">
                          <h3 className="rca-subhead">
                            {isAdminUser && adminPlant
                              ? `Plant ${adminPlant} work centres`
                              : "SBU work centres"}
                          </h3>
                          <p className="rca-section-note">
                            Ops are matched to your{" "}
                            {isAdminUser && adminPlant ? "plant" : "SBU"} catalogue
                            (keywords / capability tags). Unresolved links show as review flags —
                            edit the route card to pick a WC.
                          </p>
                          <div className="rca-machines">
                            {(wcCatalog.length ? wcCatalog : []).slice(0, 8).map((wc) => (
                              <div className="rca-machine" key={wc.id}>
                                <Tag value={wc.mode || "WC"} />
                                <h4>
                                  {wc.code} — {wc.name}
                                </h4>
                                <p>
                                  {wc.isShared ? "Shared · " : ""}
                                  {(wc.machines || []).length} machine(s)
                                </p>
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
                      <div className="flex justify-content-end gap-2 mb-2 flex-wrap">
                        
                        <Button
                          type="button"
                          label="Merge same WC"
                          icon="pi pi-objects-column"
                          outlined
                          size="small"
                          disabled={opsReadOnly || iedFieldsOnly || !canMergeSameWc}
                          onClick={mergeSameWcOps}
                          tooltip={
                            canMergeSameWc
                              ? `Merge consecutive same-WC ops (${sameWcMergePreview.beforeCount} → ${sameWcMergePreview.afterCount})`
                              : "No consecutive operations share the same work centre"
                          }
                          tooltipOptions={{ position: "top" }}
                        />
                        <Button
                          type="button"
                          label="Merge selected"
                          icon="pi pi-compress"
                          outlined
                          size="small"
                          disabled={
                            opsReadOnly || iedFieldsOnly || (selectedRouteOps?.length || 0) < 2
                          }
                          onClick={mergeSelectedOps}
                          tooltip="Merge consecutive selected ops into one (any WC)"
                          tooltipOptions={{ position: "top" }}
                        />
                        <Button
                          type="button"
                          label="Add from template"
                          icon="pi pi-list"
                          outlined
                          size="small"
                          disabled={opsReadOnly || iedFieldsOnly}
                          onClick={() => setTplPickerOpen(true)}
                        />
                        <Button
                          type="button"
                          label="Add operation"
                          icon="pi pi-plus"
                          outlined
                          size="small"
                          disabled={opsReadOnly || iedFieldsOnly}
                          onClick={() => openEdit(null)}
                        />
                      </div>
                      <DataTable
                        className="rca-data-table"
                        value={routeOps}
                        size="small"
                        paginator
                        rows={10}
                        rowsPerPageOptions={[10, 25, 50, 100]}
                        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
                        currentPageReportTemplate="{first}-{last} of {totalRecords}"
                        emptyMessage="No operations. Select consecutive rows to merge."
                        dataKey="id"
                        {...(opsReadOnly || iedFieldsOnly
                          ? {}
                          : {
                              selection: selectedRouteOps,
                              onSelectionChange: (e) => setSelectedRouteOps(e.value || []),
                              selectionMode: "checkbox",
                            })}
                      >
                        {opsReadOnly || iedFieldsOnly ? null : (
                          <Column selectionMode="multiple" headerStyle={{ width: "2.5rem" }} />
                        )}
                        <Column field="opNo" header="Op No." style={{ width: "5rem" }} />
                        <Column field="operation" header="Operation" />
                        <Column field="workCentre" header="Work centre" />
                        <Column field="machine" header="Machine" />
                        <Column
                          header=""
                          style={{ width: "7rem" }}
                          body={(row) => (
                            <div className="flex gap-1">
                              <Button
                                type="button"
                                icon="pi pi-pencil"
                                rounded
                                text
                                size="small"
                                disabled={opsReadOnly}
                                onClick={() => openEdit(row)}
                              />
                              <Button
                                type="button"
                                icon="pi pi-trash"
                                rounded
                                text
                                size="small"
                                severity="danger"
                                disabled={opsReadOnly || iedFieldsOnly}
                                onClick={() => removeOp(row)}
                              />
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
                      rowsPerPageOptions={[10, 25, 50, 100]}
                      paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
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
                      value={reviewStatusLabel === "—" ? "Pending" : reviewStatusLabel}
                      severity={reviewTagSeverity}
                    />
                  </span>
                }
              >
                <div id="rca-sec-review">
                  <p style={{ marginTop: 0, color: "var(--pmf-text-muted)", fontSize: "0.9rem" }}>
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
                  {(reviewFlags || []).length > 0 && (
                    <div className="mb-3">
                      <h4 style={{ marginBottom: "0.5rem" }}>Needs review</h4>
                      <ul style={{ paddingLeft: "1.1rem", margin: 0 }}>
                        {reviewFlags.map((f) => (
                          <li key={f.id} style={{ marginBottom: 6 }}>
                            <label className="flex align-items-start gap-2" style={{ cursor: "pointer" }}>
                              <Checkbox
                                checked={!!f.resolved}
                                onChange={(e) => toggleFlag(f, e.checked)}
                              />
                              <span>
                                <Tag
                                  value={f.severity}
                                  severity={
                                    f.severity === "high"
                                      ? "danger"
                                      : f.severity === "medium"
                                        ? "warning"
                                        : "info"
                                  }
                                  className="mr-2"
                                />
                                {f.message}
                              </span>
                            </label>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {itemLinkReport?.rows?.length > 0 && (
                    <div className="mb-3">
                      <h4 style={{ marginBottom: "0.5rem" }}>PL ↔ GA items</h4>
                      <DataTable
                        value={itemLinkReport.rows}
                        size="small"
                        paginator
                        rows={10}
                        rowsPerPageOptions={[10, 25, 50, 100]}
                        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
                        currentPageReportTemplate="{first}-{last} of {totalRecords}"
                      >
                        <Column field="itemNo" header="Item" style={{ width: 70 }} />
                        <Column field="description" header="Description" />
                        <Column field="status" header="Status" style={{ width: 100 }} />
                      </DataTable>
                    </div>
                  )}
                  {routeCardId ? (
                    <div className="mb-3">
                      <h4 style={{ marginBottom: "0.5rem" }}>Remarks</h4>
                      <RouteRemarksPanel routeCardId={routeCardId} compact />
                    </div>
                  ) : null}
                  <div className="flex gap-2 flex-wrap">
                    <Button
                      type="button"
                      label="Save Draft"
                      icon="pi pi-save"
                      outlined
                      size="small"
                      onClick={saveDraft}
                      disabled={
                        !routeCardId ||
                        reviewStatus === "ied_review" ||
                        reviewStatus === "ied_complete" ||
                        reviewStatus === "approved"
                      }
                    />
                    {canShareToIed && (
                      <Button
                        type="button"
                        label="Share to IED for review"
                        icon="pi pi-send"
                        size="small"
                        onClick={shareToIed}
                      />
                    )}
                    {canCompleteIed && (
                      <Button
                        type="button"
                        label="Complete IED review"
                        icon="pi pi-check-circle"
                        size="small"
                        onClick={completeIed}
                      />
                    )}
                    {canRecallIed && (
                      <Button
                        type="button"
                        label="Recall from IED"
                        icon="pi pi-replay"
                        outlined
                        size="small"
                        onClick={recallIed}
                      />
                    )}
                    <Button
                      type="button"
                      label="Approve"
                      icon="pi pi-check"
                      size="small"
                      disabled={!canApprove}
                      onClick={() => approveCard(false)}
                    />
                    {canAdminOverrideApprove && (
                      <Button
                        type="button"
                        label="Admin override approve"
                        icon="pi pi-shield"
                        outlined
                        severity="warning"
                        size="small"
                        onClick={() => approveCard(true)}
                      />
                    )}
                    <Button type="button" label="Download for Create Order" icon="pi pi-download" outlined size="small" onClick={downloadCreateOrder} disabled={!routeCardId} />
                    <Button type="button" label="Copy JSON" icon="pi pi-copy" outlined size="small" onClick={copyCreateOrder} disabled={!routeCardId} />
                    <Button
                      type="button"
                      label="Favorite"
                      icon="pi pi-star"
                      outlined
                      size="small"
                      disabled={!sessionId}
                      onClick={async () => {
                        await addFavorite({
                          sessionId,
                          routeCardId,
                          partNumber: drawingInfo?.partNumber || "",
                          label: drawingInfo?.partName || drawingInfo?.drawingNumber || `Session ${sessionId}`,
                        });
                        const fav = await fetchFavorites();
                        setFavorites(fav.items || []);
                        toast.success("Saved to favorites");
                      }}
                    />
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
        sessionId={sessionId}
        mode="preview"
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

      <ExcelPreviewDialog
        visible={Boolean(excelPreview)}
        blob={excelPreview?.blob || null}
        filename={excelPreview?.name || ""}
        onHide={() => setExcelPreview(null)}
      />

      <Dialog
        header="Existing extraction found"
        visible={priorDialog.visible}
        onHide={() => setPriorDialog((s) => ({ ...s, visible: false }))}
        className="rca-prior-dialog"
        style={{ width: "min(92vw, 28rem)" }}
        footer={
          <div className="oarc-instr-dialog__footer" style={{ flexWrap: "wrap" }}>
            <Button
              type="button"
              label="Cancel"
              outlined
              size="small"
              onClick={() => setPriorDialog((s) => ({ ...s, visible: false }))}
            />
            <Button
              type="button"
              label="View existing"
              icon="pi pi-folder-open"
              size="small"
              outlined
              disabled={!priorDialog.matches?.[0]?.sessionId}
              onClick={() => {
                const sid = priorDialog.matches?.[0]?.sessionId;
                setPriorDialog((s) => ({ ...s, visible: false }));
                if (sid) openSessionById(sid);
              }}
            />
            <Button
              type="button"
              label="Extract again"
              icon="pi pi-bolt"
              size="small"
              onClick={() => {
                setPriorDialog((s) => ({ ...s, visible: false }));
                proceedGenerate();
              }}
            />
          </div>
        }
      >
        <p className="oarc-instr-dialog__hint" style={{ marginBottom: "0.65rem" }}>
          Data was already extracted for this GA
          {priorDialog.matches?.[0]?.partNumber
            ? ` (part ${priorDialog.matches[0].partNumber})`
            : ""}
          . Open the existing extraction or run generate again.
        </p>
        <ul className="rca-prior-list" style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.8rem" }}>
          {(priorDialog.matches || []).slice(0, 5).map((m) => (
            <li key={m.sessionId} style={{ marginBottom: "0.35rem" }}>
              <button
                type="button"
                className="p-link"
                style={{ fontSize: "0.8rem" }}
                onClick={() => {
                  setPriorDialog((s) => ({ ...s, visible: false }));
                  openSessionById(m.sessionId);
                }}
              >
                Session {m.sessionId}
                {m.partNumber ? ` · ${m.partNumber}` : ""}
                {m.matchedFilenames?.length ? ` · ${m.matchedFilenames[0]}` : ""}
                {m.routeStatus ? ` · ${m.routeStatus}` : ""}
              </button>
            </li>
          ))}
        </ul>
      </Dialog>

      <Dialog
        header={plantDialog.mode === "relink" ? "Select plant to re-link" : "Select plant"}
        visible={plantDialog.visible}
        onHide={() => setPlantDialog((s) => ({ ...s, visible: false }))}
        className="rca-plant-dialog"
        style={{ width: "min(92vw, 22rem)" }}
        footer={
          <div className="oarc-instr-dialog__footer">
            <Button
              type="button"
              label="Cancel"
              outlined
              size="small"
              onClick={() => setPlantDialog((s) => ({ ...s, visible: false }))}
            />
            <Button
              type="button"
              label={plantDialog.mode === "relink" ? "Re-link" : "Generate"}
              icon={plantDialog.mode === "relink" ? "pi pi-link" : "pi pi-bolt"}
              size="small"
              loading={plantsLoading}
              disabled={!plantDialog.draft || plantsLoading}
              onClick={confirmAdminPlant}
            />
          </div>
        }
      >
        <p className="oarc-instr-dialog__hint" style={{ marginBottom: "0.75rem" }}>
          Work centres are linked from the selected plant catalogue.
        </p>
        <label className="om-input__label" htmlFor="rca-admin-plant" style={{ fontSize: "0.8rem" }}>
          Plant
        </label>
        <Dropdown
          inputId="rca-admin-plant"
          className="w-full"
          value={plantDialog.draft || null}
          options={plants.map((p) => ({
            label: p.label || `${p.code}${p.name ? ` — ${p.name}` : ""}`,
            value: p.code,
          }))}
          onChange={(e) => setPlantDialog((s) => ({ ...s, draft: e.value || "" }))}
          placeholder={plantsLoading ? "Loading plants…" : "Select plant"}
          filter={plants.length > 8}
          filterPlaceholder="Search plant"
          disabled={plantsLoading}
        />
      </Dialog>

      <Dialog
        header={activeDrawing?.name ? `Drawing viewer — ${activeDrawing.name}` : "Drawing viewer"}
        visible={viewerOpen}
        onHide={() => setViewerOpen(false)}
        style={{ width: "min(92vw, 56rem)" }}
        maximizable
      >
        {drawingTabs}
        <div style={{ height: "70vh" }}>
          <DrawingPreview url={previewUrl} fileType={activeDrawing?.type} />
        </div>
      </Dialog>

      <Dialog
        header={instrDialog.title || "Operation instruction"}
        visible={instrDialog.visible}
        onHide={() => {
          setInstrDialog({
            visible: false,
            opKey: null,
            title: "",
            draft: "",
            itemsUsed: [],
            viewRefs: [],
          });
          setTableCrops([]);
          setTableCropView(null);
        }}
        className="oarc-instr-dialog rca-instr-dialog"
        style={{ width: "min(94vw, 42rem)" }}
        footer={
          <div className="oarc-instr-dialog__footer">
            <Button
              type="button"
              label="Cancel"
              outlined
              size="small"
              onClick={() => {
                setInstrDialog({
                  visible: false,
                  opKey: null,
                  title: "",
                  draft: "",
                  itemsUsed: [],
                  viewRefs: [],
                });
                setTableCrops([]);
                setTableCropView(null);
              }}
            />
            <Button
              type="button"
              label="Save"
              icon="pi pi-check"
              size="small"
              onClick={saveSuggestedInstruction}
            />
          </div>
        }
      >
        <p className="oarc-instr-dialog__hint">
          Operator instructions. Click the text to edit. Item names from the Parts List appear in
          preview only — they are not written into the saved text.
        </p>
        <InstructionClickEdit
          value={instrDialog.draft}
          onChange={(e) => setInstrDialog((s) => ({ ...s, draft: e.target.value }))}
          itemLookup={plItemLookup}
          resetKey={`${instrDialog.visible}:${instrDialog.opKey || ""}`}
          rows={6}
        />
        {tableCropsLoading ? (
          <p className="oarc-instr-dialog__hint" style={{ marginTop: "0.5rem" }}>
            Checking drawing for table snapshot…
          </p>
        ) : null}
        {tableCrops.length > 0 ? (
          <div className="oarc-instr-dialog__meta" aria-label="Drawing table snapshots">
            <span className="oarc-instr-dialog__meta-label">Tables:</span>
            <div className="oarc-instr-dialog__chips">
              {tableCrops.map((crop) => (
                <Button
                  key={`${crop.drawingId}-${crop.label}`}
                  type="button"
                  label={crop.label}
                  icon="pi pi-info-circle"
                  size="small"
                  outlined
                  className="p-button-sm"
                  onClick={() =>
                    setTableCropView({
                      label: crop.label,
                      src: crop.src,
                      filename: crop.filename,
                      page: crop.page,
                      confidence: crop.confidence,
                    })
                  }
                />
              ))}
            </div>
          </div>
        ) : null}
        {(instrDialog.itemsUsed || []).length > 0 ? (
          <div className="oarc-instr-dialog__meta" aria-label="Items from Parts List">
            <span className="oarc-instr-dialog__meta-label">Items:</span>
            <div className="oarc-instr-dialog__chips">
              {(instrDialog.itemsUsed || []).map((item, idx) => (
                <span key={`${item.itemNo}-${idx}`} className="oarc-instr-chip oarc-instr-chip--item">
                  {formatItemChip(item, plItemLookup)}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </Dialog>

      <Dialog
        header={
          tableCropView
            ? `${tableCropView.label}${
                tableCropView.filename ? ` — ${tableCropView.filename}` : ""
              }${tableCropView.page ? ` (sheet ${tableCropView.page})` : ""}`
            : "Table"
        }
        visible={Boolean(tableCropView)}
        onHide={() => setTableCropView(null)}
        style={{ width: "min(96vw, 42rem)" }}
        className="rca-table-crop-dialog"
        footer={
          <div className="oarc-instr-dialog__footer">
            <Button
              type="button"
              label="Close"
              size="small"
              outlined
              onClick={() => setTableCropView(null)}
            />
          </div>
        }
      >
        {tableCropView?.src ? (
          <div className="rca-table-crop">
            <img
              src={tableCropView.src}
              alt={tableCropView.label || "Table crop"}
              className="rca-table-crop__img"
            />
            <p className="oarc-instr-dialog__hint" style={{ marginTop: "0.5rem" }}>
              Snapshot from the uploaded drawing (not OCR). Shown only when the table caption was
              found uniquely.
            </p>
          </div>
        ) : null}
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
            <Button
              type="button"
              label="Save"
              icon="pi pi-check"
              size="small"
              disabled={opsReadOnly}
              onClick={saveEdit}
            />
          </div>
        }
      >
        {editRow && (
          <div className="grid formgrid p-fluid">
            <div className="field col-12">
              <label htmlFor="rca-operation">Operation</label>
              <SafeInputText
                profile="text"
                id="rca-operation"
                value={editRow.operation ?? ""}
                disabled={opsReadOnly}
                onChange={(e) => setEditRow((r) => ({ ...r, operation: e.target.value }))}
              />
            </div>
            <div className="field col-12 md:col-6">
              <label htmlFor="rca-workCentre">Work centre</label>
              {wcDropdownOptions.length > 0 ? (
                <Dropdown
                  inputId="rca-workCentre"
                  className="w-full rca-edit-dropdown"
                  panelClassName="rca-edit-dropdown-panel"
                  appendTo={typeof document !== "undefined" ? document.body : null}
                  value={
                    editRow.workCentreId != null && editRow.workCentreId !== ""
                      ? Number(editRow.workCentreId)
                      : null
                  }
                  options={wcDropdownOptions}
                  optionLabel="label"
                  optionValue="value"
                  placeholder="Select work centre"
                  showClear
                  filter={wcDropdownOptions.length > 8}
                  filterPlaceholder="Search…"
                  scrollHeight="12rem"
                  disabled={opsReadOnly}
                  onChange={(e) => {
                    const id = e.value != null && e.value !== "" ? Number(e.value) : null;
                    const wc = (wcCatalog || []).find((w) => Number(w.id) === id);
                    setEditRow((r) => ({
                      ...r,
                      workCentreId: id,
                      workCentre: wc ? wc.code || wc.name : "",
                      workCentreName: wc?.name || "",
                      machineId: null,
                      machine: "",
                      linkStatus: "manual_override",
                    }));
                  }}
                />
              ) : (
                <SafeInputText
                  profile="text"
                  id="rca-workCentre"
                  value={editRow.workCentre ?? ""}
                  disabled={opsReadOnly}
                  onChange={(e) =>
                    setEditRow((r) => ({
                      ...r,
                      workCentre: e.target.value,
                      workCentreId: null,
                      linkStatus: "manual_override",
                    }))
                  }
                />
              )}
            </div>
            <div className="field col-12 md:col-6">
              <label htmlFor="rca-machine">Machine</label>
              {machineOptionsForEdit.length > 0 ? (
                <Dropdown
                  inputId="rca-machine"
                  className="w-full rca-edit-dropdown"
                  panelClassName="rca-edit-dropdown-panel"
                  appendTo={typeof document !== "undefined" ? document.body : null}
                  value={
                    editRow.machineId != null && editRow.machineId !== ""
                      ? Number(editRow.machineId)
                      : null
                  }
                  options={machineOptionsForEdit.map((o) => ({
                    ...o,
                    value: Number(o.value),
                  }))}
                  optionLabel="label"
                  optionValue="value"
                  placeholder="Select machine"
                  showClear
                  scrollHeight="10rem"
                  disabled={opsReadOnly}
                  onChange={(e) => {
                    const id = e.value != null && e.value !== "" ? Number(e.value) : null;
                    const m = machineOptionsForEdit.find((o) => Number(o.value) === id)?.raw;
                    setEditRow((r) => ({
                      ...r,
                      machineId: id,
                      machine: m?.name || "",
                      linkStatus: "manual_override",
                    }));
                  }}
                />
              ) : (
                <SafeInputText
                  profile="text"
                  id="rca-machine"
                  value={editRow.machine ?? ""}
                  disabled={opsReadOnly}
                  onChange={(e) =>
                    setEditRow((r) => ({
                      ...r,
                      machine: e.target.value,
                      machineId: null,
                      linkStatus: "manual_override",
                    }))
                  }
                />
              )}
            </div>
            {[
              ["tool", "Tool"],
              ["items", "Items"],
              ["torqueSpec", "Torque"],
              ["reference", "Reference"],
              ["setup", "Setup (std)"],
              ["time", "Per-piece time"],
              ["inspection", "Inspection"],
            ].map(([key, label]) => {
              const iedKey = key === "setup" || key === "time";
              const fieldDisabled = opsReadOnly || (iedFieldsOnly && !iedKey);
              return (
              <div className="field col-12 md:col-6" key={key}>
                <label htmlFor={`rca-${key}`}>{label}</label>
                <SafeInputText
                  profile="text"
                  id={`rca-${key}`}
                  value={editRow[key] ?? ""}
                  disabled={fieldDisabled}
                  onChange={(e) => setEditRow((r) => ({ ...r, [key]: e.target.value }))}
                />
              </div>
              );
            })}
            <div className="field col-12">
              <label htmlFor="rca-instructionText">Operation instruction</label>
              <SafeInputTextarea
                profile="multiline"
                id="rca-instructionText"
                rows={4}
                value={editRow.instructionText ?? ""}
                disabled={opsReadOnly || iedFieldsOnly}
                onChange={(e) => setEditRow((r) => ({ ...r, instructionText: e.target.value }))}
              />
            </div>
          </div>
        )}
      </Dialog>
    </AppShell>
  );
}
