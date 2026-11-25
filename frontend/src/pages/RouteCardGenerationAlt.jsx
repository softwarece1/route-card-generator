import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "primereact/button";
import { Column } from "primereact/column";
import { DataTable } from "primereact/datatable";
import { Dialog } from "primereact/dialog";
import { confirmDialog } from "primereact/confirmdialog";
import SafeInputText from "@/components/SafeInputText";
import { Message } from "primereact/message";
import { OverlayPanel } from "primereact/overlaypanel";
import { ProgressBar } from "primereact/progressbar";
import { TabPanel, TabView } from "primereact/tabview";
import { Tag } from "primereact/tag";
import { Dropdown } from "primereact/dropdown";
import { InputNumber } from "primereact/inputnumber";
import { toast } from "@/lib/toast";
import { getVlmPageIndexes } from "@/lib/vlmPrefs";
import { isExcelFilename, triggerBlobDownload } from "@/lib/excelPreview";
import {
  addFavorite,
  analyzeSession,
  completeIedReview,
  cancelAnalyzeSession,
  openAnalyzeProgressStream,
  createSession,
  deleteSessionDocument,
  fetchDrawingFileBlob,
  fetchDrawingViewCrop,
  fetchFavorites,
  fetchItemLinkReport,
  fetchMachinesQuietly,
  fetchMyExtractionDetail,
  fetchPlants,
  fetchPriorExtractions,
  fetchRecent,
  fetchRefDocCatalog,
  fetchRefDocumentBlob,
  fetchReviewFlags,
  fetchSessionDocumentBlob,
  fetchWorkCenterCatalog,
  getSession,
  isCanceledError,
  learnFormatTemplate,
  recallIedReview,
  relinkSessionWorkCentres,
  resolveRefDocs,
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
import PmfAnalyzeLoader from "@/components/PmfAnalyzeLoader";
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
import {
  extractRefCandidateCodes,
  indexFoundRefDocs,
  renderTextWithRefDocLinks,
} from "@/lib/refDocLinks";
import { normalizeInstructionCase, sanitizeOperatorInstruction } from "@/lib/instructionCase";
import {
  collectViewCropHints,
  resolveDrawingIdForViewHint,
} from "@/lib/tableViewHints";
import InstructionClickEdit from "@/components/InstructionClickEdit";
import "@/pages/reference-sheets.scss";
import "@fontsource/rubik/400.css";
import "@fontsource/rubik/500.css";
import "@fontsource/rubik/600.css";
import "@fontsource/rubik/700.css";
import "@fontsource/rubik/800.css";
import "./route-card-generation-alt.scss";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ADMIN_PLANT_LS_KEY = "pmf.admin.generatePlant";

/** Normalize part / drawing ids so "1120 059 762 42" and "112005976242" match. */
function chipIdentityKey(value) {
  return String(value || "")
    .replace(/[\s\-_/]/g, "")
    .toLowerCase();
}

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
  setup: "",
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

/** Map live analyze progress into the Analysis-tab task bars. */
function taskProgressFromAnalyzeStatus(status, hasWl, hasPl) {
  const pct = Math.max(0, Math.min(100, Number(status?.progress) || 0));
  const msg = String(status?.message || "").toLowerCase();
  const next = {
    ocr: 0,
    notes: 0,
    bom: 0,
    torque: 0,
    dims: 0,
    mind: 0,
    wl: hasWl ? 0 : undefined,
    pl: hasPl ? 0 : undefined,
    route: 0,
  };
  if (hasWl) {
    if (pct >= 14 || msg.includes("wire")) next.wl = pct >= 14 ? 100 : Math.max(20, pct * 6);
    if (pct >= 14) next.wl = 100;
  }
  if (hasPl) {
    if (pct >= 18 || msg.includes("parts list") || msg.includes("pl items")) {
      next.pl = pct >= 28 ? 100 : Math.max(25, Math.round(((pct - 14) / 14) * 100));
    }
    if (pct >= 28) next.pl = 100;
  }
  if (pct >= 30 || msg.includes("scanning ga") || msg.includes("drawing layout")) {
    next.ocr = Math.min(100, Math.round(((pct - 28) / 20) * 100));
  }
  if (pct >= 36 || msg.includes("notes")) {
    next.notes = Math.min(100, Math.round(((pct - 34) / 20) * 100));
  }
  if (pct >= 40 || msg.includes("quality") || msg.includes("inspection")) {
    next.torque = Math.min(100, Math.round(((pct - 38) / 15) * 100));
    next.dims = Math.min(100, Math.round(((pct - 38) / 18) * 100));
  }
  if (pct >= 50 || msg.includes("balloon") || msg.includes("drawing mind") || msg.includes("layout")) {
    next.mind = Math.min(100, Math.round(((pct - 48) / 25) * 100));
    next.bom = Math.min(100, Math.round(((pct - 55) / 25) * 100));
  }
  if (pct >= 78 || msg.includes("cross-checking") || msg.includes("linked to ga")) {
    next.bom = Math.max(next.bom, Math.min(100, Math.round(((pct - 74) / 10) * 100)));
  }
  if (pct >= 85 || msg.includes("route") || msg.includes("finishing") || msg.includes("complete")) {
    next.route = Math.min(100, Math.round(((pct - 84) / 16) * 100));
  }
  if (pct >= 98) {
    Object.keys(next).forEach((k) => {
      if (next[k] != null) next[k] = 100;
    });
  }
  // Drop undefined keys (no WL/PL)
  return Object.fromEntries(Object.entries(next).filter(([, v]) => v != null));
}

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

/** PL qty vs GA balloon/callout qty — true match, false mismatch, null unknown. */
function bomQtyMatchState(row) {
  if (!row || typeof row !== "object") return null;
  const presence = String(row.gaPresence || "").toLowerCase();
  if (presence === "not_present" || row.onDrawing === false) return null;
  if (row.qtyMatch === true) return true;
  if (row.qtyMatch === false) return false;
  const pl = row.qty;
  const ga = row.extractedQty;
  if (pl == null || pl === "" || ga == null || ga === "") return null;
  const plN = Number(pl);
  const gaN = Number(ga);
  if (!Number.isFinite(plN) || !Number.isFinite(gaN)) return null;
  return plN === gaN;
}

function bomGaPresence(row) {
  if (!row || typeof row !== "object") return "unknown";
  const p = String(row.gaPresence || "").toLowerCase();
  if (p === "present" || p === "not_present" || p === "ga_only") return p;
  if (row.onDrawing === false) return "not_present";
  if (row.onDrawing === true) return "present";
  if (row.extractedQty != null && row.extractedQty !== "") return "present";
  return "unknown";
}

function formatBomQty(value) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : String(value);
}

/**
 * BOM / PL table: always 4 digits (0010).
 * GA balloons still use short form (10, 60, 450) — matching is numeric.
 */
function formatBomItemNo(rowOrValue) {
  if (rowOrValue != null && typeof rowOrValue === "object") {
    if (rowOrValue.itemNoDisplay) return String(rowOrValue.itemNoDisplay);
    rowOrValue = rowOrValue.itemNo;
  }
  if (rowOrValue == null || rowOrValue === "") return "—";
  const n = Number(rowOrValue);
  if (!Number.isFinite(n) || n <= 0) return String(rowOrValue);
  return String(Math.trunc(n)).padStart(4, "0");
}

function formatBomDescription(row) {
  const d = row?.description;
  if (d == null || d === "") return "—";
  return String(d).toUpperCase();
}

/** Stable PL item-no order (backend already sorts; keep client defensive). */
function sortBomByItemNo(rows) {
  return [...(rows || [])].sort((a, b) => {
    const an = Number(a?.itemNo);
    const bn = Number(b?.itemNo);
    const aOk = Number.isFinite(an);
    const bOk = Number.isFinite(bn);
    if (aOk && bOk) return an - bn;
    if (aOk) return -1;
    if (bOk) return 1;
    return 0;
  });
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
  const [analyzeStatus, setAnalyzeStatus] = useState({
    message: "Please wait — preparing documents…",
    detail: "",
    progress: 0,
  });
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
  const persistOpsTimerRef = useRef(null);
  const pendingRouteOpsRef = useRef(null);
  /** Ignore InputNumber/Dropdown echo after server sync (prevents save loop). */
  const suppressOpsPersistEchoRef = useRef(false);
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
  const [viewPopoverCrop, setViewPopoverCrop] = useState(null);
  const viewPopoverRef = useRef(null);
  const [savingFormat, setSavingFormat] = useState(null);
  const [analysisPayload, setAnalysisPayload] = useState(null);
  const [oarcPreviewOpen, setOarcPreviewOpen] = useState(false);
  const [tplPickerOpen, setTplPickerOpen] = useState(false);
  const [extractedNotes, setExtractedNotes] = useState([]);
  const [mindInfo, setMindInfo] = useState(null);
  const [crossRefs, setCrossRefs] = useState([]);
  const [reviewFlags, setReviewFlags] = useState([]);
  const [showLowReviewFlags, setShowLowReviewFlags] = useState(false);
  const [showGaQtyMatch, setShowGaQtyMatch] = useState(false);
  const [itemLinkReport, setItemLinkReport] = useState(null);
  const [refFolderCodes, setRefFolderCodes] = useState([]);
  const [refDocsFound, setRefDocsFound] = useState([]);
  const [refDocPreview, setRefDocPreview] = useState(null);
  const [recentItems, setRecentItems] = useState([]);
  const [favorites, setFavorites] = useState([]);
  /** Favorites first; recent hides anything already favorited (same session or part). */
  const sessionChips = useMemo(() => {
    const favSessionIds = new Set();
    const favPartKeys = new Set();
    const favChips = [];
    for (const f of favorites || []) {
      const sid = f.sessionId != null ? Number(f.sessionId) : null;
      const partKey =
        chipIdentityKey(f.partNumber) ||
        chipIdentityKey(f.label);
      if (sid && favSessionIds.has(sid)) continue;
      if (partKey && favPartKeys.has(partKey)) continue;
      if (sid) favSessionIds.add(sid);
      if (partKey) favPartKeys.add(partKey);
      favChips.push(f);
      if (favChips.length >= 5) break;
    }

    const seenSessions = new Set();
    const seenParts = new Set();
    const recentChips = [];
    for (const r of recentItems || []) {
      const sid = r.sessionId != null ? Number(r.sessionId) : null;
      const partKey = chipIdentityKey(r.partNumber);
      if (sid && (favSessionIds.has(sid) || seenSessions.has(sid))) continue;
      if (partKey && (favPartKeys.has(partKey) || seenParts.has(partKey))) continue;
      if (sid) seenSessions.add(sid);
      if (partKey) seenParts.add(partKey);
      recentChips.push(r);
      if (recentChips.length >= 5) break;
    }
    return { recent: recentChips, favorites: favChips };
  }, [recentItems, favorites]);
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
  const [sessionSbu, setSessionSbu] = useState("");
  const [sessionPlant, setSessionPlant] = useState("");
  const analyzeAbortRef = useRef(null);
  const analyzingRef = useRef(false);
  const sessionIdRef = useRef(sessionId);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    analyzingRef.current = analyzing;
  }, [analyzing]);

  const docsRef = useRef(docs);
  useEffect(() => {
    docsRef.current = docs;
  }, [docs]);

  useEffect(() => {
    if (!analyzing || !sessionId) return undefined;
    const close = openAnalyzeProgressStream(sessionId, {
      onProgress: (snap) => {
        if (!analyzingRef.current) return;
        if (!snap?.message && snap?.progress == null && !snap?.detail) return;
        setAnalyzeStatus({
          message: snap.message || "Analyzing…",
          detail: snap.detail || "",
          progress: Number(snap.progress) || 0,
        });
        const d = docsRef.current || {};
        setTaskProgress(
          taskProgressFromAnalyzeStatus(snap, Boolean(d.wirelist), Boolean(d.partslist)),
        );
      },
    });
    return () => {
      close();
    };
  }, [analyzing, sessionId]);

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
    setBomItems(sortBomByItemNo(payload.bomItems || []));
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
    if (payload.reviewFlags) {
      setReviewFlags(payload.reviewFlags);
      setShowLowReviewFlags(false);
    }
    if (payload.itemLinkReport) setItemLinkReport(payload.itemLinkReport);
    if (payload.sbu != null) setSessionSbu(String(payload.sbu || "").trim());
    if (payload.plant != null) {
      const p = String(payload.plant || "").trim();
      setSessionPlant(p);
      if (p && getUser()?.role === "admin") {
        setAdminPlant(p);
        storeAdminPlant(p);
      }
    }
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
    const user = getUser();
    const role = user?.role || "";
    const ownSbu = String(user?.sbu || "").trim();
    const selectedSbu = (sessionSbu || "").trim();
    // Prefer session/selected SBU; fall back to the signed-in user's SBU.
    const sbu = selectedSbu || (role !== "admin" ? ownSbu : "") || undefined;
    const plant =
      (role === "admin" && (adminPlant || "").trim()) ||
      (sessionPlant || "").trim() ||
      undefined;

    (async () => {
      const [m, primary] = await Promise.all([
        fetchMachinesQuietly(),
        fetchWorkCenterCatalog(sbu || undefined, {
          plant: plant || undefined,
        }),
      ]);
      let wc = primary || [];
      // Cross-SBU catalog may 403 for non-admins — retry with own SBU.
      if (!wc.length && ownSbu && sbu && sbu !== ownSbu && role !== "admin") {
        wc = (await fetchWorkCenterCatalog(ownSbu, {})) || [];
      }
      if (!cancelled) {
        setMachines(m || []);
        setWcCatalog(wc);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [adminPlant, sessionSbu, sessionPlant]);

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

  /** Resolve dropdown value by id, else match free-text WC code/name from catalog. */
  const resolveWcDropdownValue = useCallback(
    (row) => {
      if (row?.workCentreId != null && row.workCentreId !== "") {
        const id = Number(row.workCentreId);
        if ((wcCatalog || []).some((w) => Number(w.id) === id)) return id;
      }
      const key = String(row?.workCentre || row?.workCentreName || "")
        .trim()
        .toLowerCase();
      if (!key) return null;
      const match = (wcCatalog || []).find((w) => {
        const code = String(w.code || "").trim().toLowerCase();
        const name = String(w.name || "").trim().toLowerCase();
        const sap = String(w.sapCode || "").trim().toLowerCase();
        return key === code || key === name || (sap && key === sap);
      });
      return match ? Number(match.id) : null;
    },
    [wcCatalog]
  );

  const plItemLookup = useMemo(() => {
    const map = {};
    const index = (it) => {
      if (it?.itemNo == null) return;
      const n = Number(it.itemNo);
      if (!Number.isFinite(n) || n <= 0) {
        map[String(it.itemNo)] = { ...map[String(it.itemNo)], ...it };
        return;
      }
      const unpadded = String(Math.trunc(n));
      const padded = unpadded.padStart(4, "0");
      // Index both GA short form (60) and PL form (0060)
      map[unpadded] = { ...map[unpadded], ...it };
      map[padded] = { ...map[padded], ...it };
      if (it.itemNoDisplay) map[String(it.itemNoDisplay)] = map[padded];
    };
    for (const it of partsListSummary?.items || []) index(it);
    for (const it of bomItems || []) {
      if (!it?.description && it?.itemNo == null) continue;
      index(it);
    }
    return map;
  }, [partsListSummary, bomItems]);

  const refDocsByCode = useMemo(() => indexFoundRefDocs(refDocsFound), [refDocsFound]);

  /** Instruction text only — avoids re-resolve on every inline op/WC/time keystroke. */
  const refDocScanText = useMemo(() => {
    const chunks = [];
    for (const n of extractedNotes || []) {
      chunks.push(n?.text || "", n?.elaboratedText || "");
    }
    for (const op of suggestedOps || []) {
      chunks.push(op?.instructionText || "", op?.reason || "");
    }
    for (const op of routeOps || []) {
      chunks.push(op?.instructionText || "", op?.reason || "");
    }
    return chunks.join("\n");
  }, [extractedNotes, suggestedOps, routeOps]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cat = await fetchRefDocCatalog();
        if (!cancelled) setRefFolderCodes(cat?.folderCodes || []);
      } catch {
        if (!cancelled) setRefFolderCodes([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!refFolderCodes.length) {
      setRefDocsFound([]);
      return;
    }
    const codes = extractRefCandidateCodes(refDocScanText, refFolderCodes);
    if (!codes.length) {
      setRefDocsFound([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await resolveRefDocs(codes);
        if (!cancelled) setRefDocsFound(res?.found || []);
      } catch {
        if (!cancelled) setRefDocsFound([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refDocScanText, refFolderCodes]);

  useEffect(
    () => () => {
      if (refDocPreview?.url) URL.revokeObjectURL(refDocPreview.url);
    },
    [refDocPreview?.url],
  );

  const openRefDoc = useCallback(async (row) => {
    if (!row?.documentId && !row?.id) return;
    const documentId = row.documentId ?? row.id;
    try {
      if (refDocPreview?.url) URL.revokeObjectURL(refDocPreview.url);
      const blob = await fetchRefDocumentBlob(documentId);
      const url = URL.createObjectURL(blob);
      setRefDocPreview({
        url,
        title: row.code || row.docCode || `Doc ${documentId}`,
        filename: row.name || row.originalFilename || `${row.code || "sheet"}.pdf`,
        documentId,
      });
    } catch (e) {
      toast.error(e.message || "Could not open reference sheet");
    }
  }, [refDocPreview?.url]);

  const downloadRefDoc = useCallback(async (row) => {
    if (!row?.documentId && !row?.id) return;
    const documentId = row.documentId ?? row.id;
    try {
      const blob = await fetchRefDocumentBlob(documentId);
      const name = row.name || row.originalFilename || `${row.code || row.docCode || "sheet"}.pdf`;
      triggerBlobDownload(blob, name);
    } catch (e) {
      toast.error(e.message || "Could not download reference sheet");
    }
  }, []);

  const ensureSession = async () => {
    // Ref, not state: a multi-file batch must reuse the session created by the first file.
    if (sessionIdRef.current) return sessionIdRef.current;
    const s = await createSession();
    sessionIdRef.current = s.id;
    setSessionId(s.id);
    if (s.sbu != null) setSessionSbu(String(s.sbu || "").trim());
    if (s.plant != null) setSessionPlant(String(s.plant || "").trim());
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
    setSessionSbu("");
    setSessionPlant("");
    setZoom(1);
    setAnalyzing(false);
    setAnalyzeStatus({ message: "", detail: "", progress: 0 });
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
      setAnalyzeStatus({ message: "", detail: "", progress: 0 });
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
    setAnalyzeStatus({ message: "", detail: "", progress: 0 });
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
    setAnalyzeStatus({
      message: "Please wait — preparing documents…",
      detail: "",
      progress: 0,
    });
    setTaskProgress({
      ocr: 5,
      notes: 0,
      bom: 0,
      torque: 0,
      dims: 0,
      mind: 0,
      ...(docs.wirelist ? { wl: 5 } : {}),
      ...(docs.partslist ? { pl: 5 } : {}),
      route: 0,
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
      setAnalyzeStatus({
        message: "Analysis complete",
        detail: "",
        progress: 100,
      });
      setAnalyzing(false);
      setAnalyzed(true);
      setResultTab(1);
      toast.success("OARC generated. Review the results in the tabs below.");
    } catch (error) {
      setAnalyzing(false);
      setAnalyzeStatus({ message: "", detail: "", progress: 0 });
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

  const clearPersistOpsTimer = () => {
    if (persistOpsTimerRef.current) {
      clearTimeout(persistOpsTimerRef.current);
      persistOpsTimerRef.current = null;
    }
    pendingRouteOpsRef.current = null;
  };

  const syncRouteStatusFromPayload = (payload) => {
    if (!payload) return;
    if (payload.id != null) setRouteCardId(payload.id);
    const st = (payload.status || "").toLowerCase();
    if (st === "approved") setReviewStatus("approved");
    else if (st === "ied_review") setReviewStatus("ied_review");
    else if (st === "ied_complete") setReviewStatus("ied_complete");
    else if (st === "draft") setReviewStatus("draft");
    else if (st) setReviewStatus("ready");
  };

  const persistOps = async (rows) => {
    clearPersistOpsTimer();
    setRouteOps(rows);
    if (!routeCardId) return;
    try {
      const payload = await updateRouteCard(routeCardId, {
        operations: rows,
        inspection: inspectionChars,
      });
      syncRouteStatusFromPayload(payload);
      const serverOps = payload?.routeOperations;
      if (Array.isArray(serverOps) && serverOps.length) {
        const needsIdSync = serverOps.some(
          (s, i) => String(s?.id) !== String(rows[i]?.id)
        );
        if (needsIdSync) {
          suppressOpsPersistEchoRef.current = true;
          setRouteOps(serverOps);
          window.setTimeout(() => {
            suppressOpsPersistEchoRef.current = false;
          }, 50);
        }
      }
    } catch (error) {
      toast.error(error.message || "Could not save operations");
      setRouteOps(rows);
    }
  };

  const updateRouteOp = (opId, patch) => {
    if (suppressOpsPersistEchoRef.current) return;
    setRouteOps((prev) => {
      const list = prev || [];
      const idx = list.findIndex((r) => String(r.id) === String(opId));
      if (idx < 0) return list;
      const row = list[idx];
      const changed = Object.keys(patch).some((k) => {
        const a = row[k];
        const b = patch[k];
        if (a === b) return false;
        if (a == null && b == null) return false;
        if (
          (k === "setup" || k === "time" || k === "workCentreId") &&
          a != null &&
          b != null &&
          Number(a) === Number(b)
        ) {
          return false;
        }
        return String(a ?? "") !== String(b ?? "");
      });
      if (!changed) return list;
      const nextRows = list.map((r, i) => (i === idx ? { ...r, ...patch } : r));
      pendingRouteOpsRef.current = nextRows;
      if (persistOpsTimerRef.current) clearTimeout(persistOpsTimerRef.current);
      persistOpsTimerRef.current = setTimeout(() => {
        persistOpsTimerRef.current = null;
        const next = pendingRouteOpsRef.current;
        pendingRouteOpsRef.current = null;
        if (next) persistOps(next);
      }, 500);
      return nextRows;
    });
  };

  const addRouteOp = async () => {
    const newOp = {
      ...EMPTY_OPERATION,
      id: `op-${Date.now()}`,
      opNo: nextOpNumber(routeOps),
    };
    const next = renumberRouteOps([...(routeOps || []), newOp]);
    await persistOps(next);
    toast.success("Route operation added.");
  };

  const onRouteOpsReorder = (e) => {
    const proposed = e.value || [];
    confirmDialog({
      header: "Reorder operations",
      message: "Reorder operations? Numbers will renumber 10, 20, 30…",
      icon: "pi pi-sort-alt",
      className: "p-confirm-dialog-sm",
      acceptLabel: "Reorder",
      rejectLabel: "Cancel",
      acceptClassName: "p-button-sm",
      rejectClassName: "p-button-sm p-button-outlined",
      accept: async () => {
        setSelectedRouteOps([]);
        await persistOps(renumberRouteOps(proposed));
        toast.success("Operations reordered.");
      },
    });
  };

  const openDetails = (row) => {
    setEditRow({ ...row });
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
      // Only this op's text + op.viewRefs — never session-wide mindInfo.viewRefs
      // (that listed every FIGURE/TABLE/DETAIL from the whole GA on every OP).
      const hints = collectViewCropHints(draft, viewRefs || []);
      setTableCrops([]);
      if (!hints.length) return;

      setTableCropsLoading(true);
      try {
        const results = [];
        for (const hint of hints) {
          const preferred = resolveDrawingIdForViewHint(hint, sessionDrawingsForCrop);
          const tryIds = [
            ...(preferred ? [preferred] : []),
            ...((sessionDrawingsForCrop || [])
              .map((d) => Number(d.id))
              .filter((id) => id && id !== preferred) || []),
          ];
          let found = null;
          for (const did of tryIds) {
            try {
              let crop = await fetchDrawingViewCrop(did, {
                kind: hint.kind,
                id: hint.refId,
                page: hint.sheet || undefined,
              });
              // Single-page sheet PDFs often use sheet no in the filename only
              if (!crop?.available && hint.sheet) {
                crop = await fetchDrawingViewCrop(did, {
                  kind: hint.kind,
                  id: hint.refId,
                });
              }
              // Gated: only keep high-confidence available crops
              if (crop?.available && crop.imageBase64) {
                found = {
                  ...crop,
                  kind: crop.kind || hint.kind,
                  refId: hint.refId,
                  label: crop.label || hint.label,
                  src: `data:${crop.mime || "image/jpeg"};base64,${crop.imageBase64}`,
                };
                break;
              }
            } catch {
              /* gated — skip unavailable */
            }
          }
          if (found) results.push(found);
        }
        setTableCrops(results);
      } finally {
        setTableCropsLoading(false);
      }
    },
    [sessionDrawingsForCrop],
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

  const saveDetails = async () => {
    if (!editRow?.id) {
      setEditVisible(false);
      return;
    }
    const nextRow = {
      ...editRow,
      linkStatus: "manual_override",
      type: editRow.workCentreName || editRow.workCentre || editRow.type,
    };
    const rows = (routeOps || []).map((r) =>
      String(r.id) === String(editRow.id) ? nextRow : r
    );
    setEditVisible(false);
    await persistOps(rows);
    toast.success("Operation details updated.");
  };

  const removeOp = async (row) => {
    const next = renumberRouteOps(
      (routeOps || []).filter((r) => String(r.id) !== String(row.id))
    );
    await persistOps(next);
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

  const reviewFlagsPrimary = (reviewFlags || []).filter((f) =>
    ["high", "medium"].includes((f.severity || "").toLowerCase()),
  );
  const reviewFlagsLow = (reviewFlags || []).filter(
    (f) => (f.severity || "").toLowerCase() === "low",
  );
  const visibleReviewFlags = showLowReviewFlags
    ? [...reviewFlagsPrimary, ...reviewFlagsLow]
    : reviewFlagsPrimary;
  const currentUser = getUser();
  const userRole = currentUser?.role;
  const isIedUser = Boolean(currentUser?.isIedDept) || userRole === "ied";
  const isAdminUser = userRole === "admin";
  const isSbuHeadUser = userRole === "sbu_head";
  const isDeptHeadUser = userRole === "dept_head";
  const canShareToIed =
    Boolean(routeCardId) &&
    (reviewStatus === "draft" || reviewStatus === "ied_complete") &&
    !isIedUser;
  const shareIedSbu =
    (sessionSbu || "").trim() ||
    (getUser()?.role === "admin"
      ? ""
      : String(getUser()?.sbu || "").trim());
  const shareToIedLabel = shareIedSbu
    ? `Share to ${shareIedSbu} IED for review`
    : "Share to IED for review";
  const canCompleteIed =
    Boolean(routeCardId) &&
    reviewStatus === "ied_review" &&
    (isIedUser || isAdminUser);
  const canRecallIed =
    Boolean(routeCardId) &&
    reviewStatus === "ied_review" &&
    (isAdminUser || isSbuHeadUser || isDeptHeadUser || !isIedUser);
  const opsReadOnly =
    reviewStatus === "approved" ||
    (reviewStatus === "ied_review" && !isIedUser && !isAdminUser) ||
    (isIedUser && reviewStatus !== "ied_review");
  const iedFieldsOnly = reviewStatus === "ied_review" && isIedUser;
  const canStructureOps = !opsReadOnly && !iedFieldsOnly;
  const canEditTimes = !opsReadOnly;

  const shareToIed = async () => {
    if (!routeCardId) return;
    try {
      const wasAlready = reviewStatus === "ied_review";
      const payload = await shareRouteToIed(routeCardId);
      applyPayload(payload);
      toast.success(
        wasAlready
          ? "Already awaiting IED review."
          : shareIedSbu
            ? `Shared to ${shareIedSbu} IED — awaiting review.`
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

  useEffect(
    () => () => {
      if (persistOpsTimerRef.current) {
        clearTimeout(persistOpsTimerRef.current);
        persistOpsTimerRef.current = null;
      }
    },
    [],
  );

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
        if (sess.sbu != null) setSessionSbu(String(sess.sbu || "").trim());
        if (sess.plant != null) setSessionPlant(String(sess.plant || "").trim());
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
          {(sessionChips.recent.length > 0 || sessionChips.favorites.length > 0) && (
            <div className="rca-session-chips flex gap-2 flex-wrap mb-2 align-items-center">
              <span className="rca-session-chips__hint">Recent / favorites — click to reopen:</span>
              {sessionChips.recent.map((r) => (
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
              {sessionChips.favorites.map((f) => (
                <Button
                  key={`f-${f.id}`}
                  type="button"
                  size="small"
                  outlined={sessionId !== f.sessionId}
                  severity={sessionId === f.sessionId ? undefined : "secondary"}
                  disabled={openingSession || !f.sessionId}
                  icon="pi pi-star"
                  label={f.partNumber || f.label || `Fav ${f.id}`}
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
                                severity="secondary"
                                size="small"
                                className="rca-slot__browse"
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
                                    {renderTextWithRefDocLinks(n.text || "—", {
                                      itemLookup: plItemLookup,
                                      foundByCode: refDocsByCode,
                                      onOpenRefDoc: openRefDoc,
                                    })}
                                  </p>
                                  {n.elaboratedText && n.elaboratedText !== n.text ? (
                                    <p className="rca-note__source">
                                      Elaborated:{" "}
                                      {renderTextWithRefDocLinks(n.elaboratedText, {
                                        itemLookup: plItemLookup,
                                        foundByCode: refDocsByCode,
                                        onOpenRefDoc: openRefDoc,
                                      })}
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
                      <div className="rca-bom-toolbar">
                        <Button
                          type="button"
                          size="small"
                          outlined={!showGaQtyMatch}
                          icon={showGaQtyMatch ? "pi pi-eye-slash" : "pi pi-eye"}
                          label={showGaQtyMatch ? "Hide GA qty" : "Show GA qty"}
                          onClick={() => setShowGaQtyMatch((v) => !v)}
                        />
                      </div>
                      {showGaQtyMatch && bomItems.some((r) => bomQtyMatchState(r) === false) ? (
                        <Message
                          severity="warn"
                          className="w-full mb-2"
                          text={`PL qty ≠ GA qty for ${
                            bomItems.filter((r) => bomQtyMatchState(r) === false).length
                          } item(s) — mismatched rows are highlighted.`}
                        />
                      ) : null}
                      <DataTable
                        key={showGaQtyMatch ? "bom-ga" : "bom-pl"}
                        className="rca-data-table rca-bom-table"
                        value={bomItems}
                        size="small"
                        paginator
                        rows={10}
                        rowsPerPageOptions={[10, 25, 50, 100]}
                        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
                        currentPageReportTemplate="{first}-{last} of {totalRecords}"
                        emptyMessage="No BOM items extracted."
                        rowClassName={(row) => {
                          const presence = bomGaPresence(row);
                          if (presence === "not_present") return "rca-bom-row--absent";
                          if (presence === "ga_only") return "rca-bom-row--ga-only";
                          if (!showGaQtyMatch) return "";
                          const m = bomQtyMatchState(row);
                          if (m === false) return "rca-bom-row--mismatch";
                          if (m === true) return "rca-bom-row--match";
                          return "";
                        }}
                      >
                        <Column
                          field="itemNo"
                          header="Item"
                          style={{ width: "5rem" }}
                          body={(row) => formatBomItemNo(row)}
                        />
                        <Column
                          field="qty"
                          header="PL qty"
                          style={{ width: "4.5rem" }}
                          body={(row) => formatBomQty(row.qty)}
                        />
                        {showGaQtyMatch ? (
                          <Column
                            field="extractedQty"
                            header={
                              <span title="Quantity summed from GA balloon / callout extraction">
                                GA qty
                              </span>
                            }
                            style={{ width: "4.5rem" }}
                            body={(row) => {
                              if (bomGaPresence(row) === "not_present") return "—";
                              return formatBomQty(row.extractedQty);
                            }}
                          />
                        ) : null}
                        <Column
                          header="On GA"
                          style={{ width: "7rem" }}
                          body={(row) => {
                            const p = bomGaPresence(row);
                            if (p === "present") {
                              return (
                                <Tag
                                  className="rca-bom-match-tag"
                                  value="Present"
                                  severity="success"
                                />
                              );
                            }
                            if (p === "not_present") {
                              return (
                                <Tag
                                  className="rca-bom-match-tag"
                                  value="Not present"
                                  severity="secondary"
                                />
                              );
                            }
                            if (p === "ga_only") {
                              return (
                                <Tag
                                  className="rca-bom-match-tag"
                                  value="GA only"
                                  severity="warning"
                                />
                              );
                            }
                            return <Tag value="—" severity="secondary" />;
                          }}
                        />
                        {showGaQtyMatch ? (
                          <Column
                            header="Match"
                            style={{ width: "6.5rem" }}
                            body={(row) => {
                              const presence = bomGaPresence(row);
                              if (presence === "not_present") {
                                return (
                                  <Tag
                                    className="rca-bom-match-tag"
                                    value="Not on GA"
                                    severity="secondary"
                                  />
                                );
                              }
                              if (presence === "ga_only") {
                                return (
                                  <Tag
                                    className="rca-bom-match-tag"
                                    value="No PL"
                                    severity="warning"
                                  />
                                );
                              }
                              const m = bomQtyMatchState(row);
                              if (m === true) {
                                return (
                                  <Tag
                                    className="rca-bom-match-tag"
                                    value="Match"
                                    severity="success"
                                    icon="pi pi-check-circle"
                                  />
                                );
                              }
                              if (m === false) {
                                return (
                                  <Tag
                                    className="rca-bom-match-tag"
                                    value="Mismatch"
                                    severity="danger"
                                    icon="pi pi-times-circle"
                                  />
                                );
                              }
                              return <Tag value="—" severity="secondary" />;
                            }}
                          />
                        ) : null}
                        <Column field="partNumber" header="Part No." />
                        <Column
                          field="description"
                          header="Description"
                          body={(row) => formatBomDescription(row)}
                        />
                        <Column
                          field="unit"
                          header="Unit"
                          style={{ width: "4rem" }}
                          body={(row) => (row.unit ? String(row.unit).toUpperCase() : "—")}
                        />
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
                                {rawInstr.trim()
                                  ? renderTextWithRefDocLinks(rawInstr, {
                                      itemLookup: plItemLookup,
                                      foundByCode: refDocsByCode,
                                      onOpenRefDoc: openRefDoc,
                                    })
                                  : "—"}
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
                              {op.drawingZone ? (
                                <div>
                                  <dt>Zone</dt>
                                  <dd>{op.drawingZone}</dd>
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
                <div id="rca-sec-route" className="om-create-order-section">
                  {!showResults ? (
                    <Message severity="info" text="Route operations appear after analysis." className="w-full" />
                  ) : (
                    <>
                      <div className="om-create-order-section__toolbar">
                        <span className="om-create-order-section__hint">
                          {!canStructureOps
                            ? canEditTimes
                              ? "Edit setup and per-piece time (in hrs) only."
                              : "Read-only — operations cannot be changed."
                            : routeOps?.length
                              ? "Drag rows to reorder. Operation numbers stay ascending (10, 20, 30…)."
                              : "No operations yet. Click Add operation to start."}
                        </span>
                        {canStructureOps ? (
                          <div className="flex gap-2 flex-wrap">
                            <Button
                              type="button"
                              label="Merge same WC"
                              icon="pi pi-objects-column"
                              outlined
                              size="small"
                              disabled={!canMergeSameWc}
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
                              disabled={(selectedRouteOps?.length || 0) < 2}
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
                              onClick={() => setTplPickerOpen(true)}
                            />
                            <Button
                              type="button"
                              label="Add operation"
                              icon="pi pi-plus"
                              size="small"
                              onClick={addRouteOp}
                            />
                          </div>
                        ) : null}
                      </div>
                      <DataTable
                        className="om-create-order-table"
                        value={routeOps}
                        dataKey="id"
                        size="small"
                        scrollable
                        scrollHeight="420px"
                        tableStyle={{ minWidth: "64rem" }}
                        reorderableRows={canStructureOps}
                        onRowReorder={canStructureOps ? onRouteOpsReorder : undefined}
                        emptyMessage={
                          <div className="om-create-order-empty">
                            <p>No operations added yet.</p>
                            <p className="om-create-order-empty__sub">
                              Click &quot;Add operation&quot; to start adding operations.
                            </p>
                          </div>
                        }
                        {...(canStructureOps
                          ? {
                              selection: selectedRouteOps,
                              onSelectionChange: (e) => setSelectedRouteOps(e.value || []),
                              selectionMode: "checkbox",
                            }
                          : {})}
                      >
                        {canStructureOps ? (
                          <Column selectionMode="multiple" headerStyle={{ width: "2.5rem" }} />
                        ) : null}
                        {canStructureOps ? (
                          <Column rowReorder style={{ width: "3rem", minWidth: "3rem" }} />
                        ) : null}
                        <Column
                          header="Op No."
                          style={{ minWidth: "5rem", width: "5rem" }}
                          body={(row) => <span className="om-oprn-no">{row.opNo}</span>}
                        />
                        <Column
                          header="Operation"
                          style={{ minWidth: "22rem" }}
                          body={(row) => {
                            const hasInstruction = Boolean(
                              String(row.instructionText || row.reason || "").trim()
                            );
                            return (
                              <div className="om-op-desc-field">
                                <SafeInputText
                                  profile="text"
                                  value={row.operation || ""}
                                  placeholder="Enter operation description"
                                  className="om-op-desc-field__input w-full"
                                  disabled={!canStructureOps}
                                  onChange={(e) =>
                                    updateRouteOp(row.id, { operation: e.target.value })
                                  }
                                />
                                <div className="om-op-desc-field__actions">
                                  <Button
                                    type="button"
                                    icon={hasInstruction ? "pi pi-file-edit" : "pi pi-align-left"}
                                    className={`om-op-instruction-btn${hasInstruction ? " om-op-instruction-btn--filled" : ""}`}
                                    rounded
                                    text
                                    size="small"
                                    disabled={!canStructureOps && !hasInstruction}
                                    tooltip={
                                      canStructureOps
                                        ? hasInstruction
                                          ? "Edit instruction"
                                          : "Add instruction"
                                        : "View instruction"
                                    }
                                    tooltipOptions={{ position: "top" }}
                                    aria-label={
                                      canStructureOps
                                        ? hasInstruction
                                          ? "Edit instruction"
                                          : "Add instruction"
                                        : "View instruction"
                                    }
                                    onClick={(event) => {
                                      event.preventDefault();
                                      event.stopPropagation();
                                      openSuggestedInstruction(row);
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
                          header="Work centre"
                          style={{ minWidth: "14rem" }}
                          body={(row) => {
                            const selectedId = resolveWcDropdownValue(row);
                            const orphanLabel = String(
                              row.workCentre || row.workCentreName || ""
                            ).trim();
                            const options =
                              selectedId != null || !orphanLabel
                                ? wcDropdownOptions
                                : [
                                    {
                                      label: `${orphanLabel} (not in SBU catalog)`,
                                      value: -1,
                                      raw: null,
                                    },
                                    ...wcDropdownOptions,
                                  ];
                            const value =
                              selectedId != null
                                ? selectedId
                                : orphanLabel
                                  ? -1
                                  : null;
                            if (!wcDropdownOptions.length && !orphanLabel) {
                              return (
                                <SafeInputText
                                  profile="text"
                                  value={row.workCentre || ""}
                                  className="w-full"
                                  placeholder="Work centre"
                                  disabled={!canStructureOps}
                                  onChange={(e) =>
                                    updateRouteOp(row.id, {
                                      workCentre: e.target.value,
                                      workCentreId: null,
                                      linkStatus: "manual_override",
                                    })
                                  }
                                />
                              );
                            }
                            if (!wcDropdownOptions.length) {
                              return (
                                <SafeInputText
                                  profile="text"
                                  value={row.workCentre || ""}
                                  className="w-full"
                                  placeholder="No SBU work centres loaded"
                                  disabled={!canStructureOps}
                                  onChange={(e) =>
                                    updateRouteOp(row.id, {
                                      workCentre: e.target.value,
                                      workCentreId: null,
                                      linkStatus: "manual_override",
                                    })
                                  }
                                />
                              );
                            }
                            return (
                              <Dropdown
                                value={value}
                                options={options}
                                optionLabel="label"
                                optionValue="value"
                                className="w-full rca-edit-dropdown"
                                panelClassName="rca-edit-dropdown-panel"
                                appendTo={
                                  typeof document !== "undefined" ? document.body : null
                                }
                                placeholder="Select work centre"
                                filter={options.length > 8}
                                filterPlaceholder="Search…"
                                showClear
                                disabled={!canStructureOps}
                                onChange={(e) => {
                                  const id =
                                    e.value != null && e.value !== "" && Number(e.value) > 0
                                      ? Number(e.value)
                                      : null;
                                  const wc = (wcCatalog || []).find(
                                    (w) => Number(w.id) === id
                                  );
                                  updateRouteOp(row.id, {
                                    workCentreId: id,
                                    workCentre: wc ? wc.code || wc.name : "",
                                    workCentreName: wc?.name || "",
                                    type: wc?.name || wc?.code || row.type || "",
                                    linkStatus: "manual_override",
                                  });
                                }}
                              />
                            );
                          }}
                        />
                        <Column
                          header="Setup time (hrs)"
                          style={{ minWidth: "8.5rem", width: "8.5rem" }}
                          body={(row) => (
                            <InputNumber
                              value={
                                row.setup === "" || row.setup == null ? null : Number(row.setup)
                              }
                              min={0}
                              mode="decimal"
                              minFractionDigits={0}
                              maxFractionDigits={3}
                              className="w-full"
                              disabled={!canEditTimes}
                              onValueChange={(e) =>
                                updateRouteOp(row.id, {
                                  setup: e.value == null ? "" : String(e.value),
                                })
                              }
                            />
                          )}
                        />
                        <Column
                          header="Per piece (hrs)"
                          style={{ minWidth: "8.5rem", width: "8.5rem" }}
                          body={(row) => (
                            <InputNumber
                              value={
                                row.time === "" || row.time == null ? null : Number(row.time)
                              }
                              min={0}
                              mode="decimal"
                              minFractionDigits={0}
                              maxFractionDigits={3}
                              className="w-full"
                              disabled={!canEditTimes}
                              onValueChange={(e) =>
                                updateRouteOp(row.id, {
                                  time: e.value == null ? "" : String(e.value),
                                })
                              }
                            />
                          )}
                        />
                        <Column
                          header=""
                          style={{ minWidth: "6.5rem", width: "6.5rem" }}
                          body={(row) => (
                            <div className="flex gap-1">
                              <Button
                                type="button"
                                icon="pi pi-ellipsis-h"
                                rounded
                                text
                                size="small"
                                disabled={!canStructureOps}
                                tooltip="Details (tool, items, …)"
                                tooltipOptions={{ position: "top" }}
                                onClick={() => openDetails(row)}
                              />
                              {canStructureOps ? (
                                <Button
                                  type="button"
                                  icon="pi pi-trash"
                                  rounded
                                  text
                                  size="small"
                                  severity="danger"
                                  onClick={() => removeOp(row)}
                                />
                              ) : null}
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
                      <div className="flex align-items-center justify-content-between gap-2 flex-wrap" style={{ marginBottom: "0.5rem" }}>
                        <h4 style={{ margin: 0 }}>Needs review</h4>
                        {reviewFlagsLow.length > 0 && (
                          <Button
                            type="button"
                            text
                            size="small"
                            className="p-0"
                            label={
                              showLowReviewFlags
                                ? "Hide diagnostics"
                                : `${reviewFlagsLow.length} diagnostic note${reviewFlagsLow.length === 1 ? "" : "s"}`
                            }
                            icon={showLowReviewFlags ? "pi pi-chevron-up" : "pi pi-chevron-down"}
                            onClick={() => setShowLowReviewFlags((v) => !v)}
                          />
                        )}
                      </div>
                      <ul style={{ paddingLeft: "1.1rem", margin: 0 }}>
                        {visibleReviewFlags.map((f) => (
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
                        {!showLowReviewFlags &&
                          reviewFlagsPrimary.length === 0 &&
                          reviewFlagsLow.length > 0 && (
                            <li style={{ marginBottom: 6, listStyle: "none", paddingLeft: 0 }}>
                              <span style={{ fontSize: "0.85rem", opacity: 0.85 }}>
                                Only low-priority drawing-mind diagnostics — expand above if needed.
                              </span>
                            </li>
                          )}
                      </ul>
                    </div>
                  )}
                  {itemLinkReport?.rows?.length > 0 && (
                    <div className="mb-3">
                      <h4 style={{ marginBottom: "0.5rem" }}>PL ↔ GA items</h4>
                      {(itemLinkReport.summary?.qtyMismatchCount > 0) && (
                        <Message
                          severity="warn"
                          className="w-full mb-2"
                          text={`PL qty ≠ extracted callout qty for ${itemLinkReport.summary.qtyMismatchCount} item(s).`}
                        />
                      )}
                      <DataTable
                        value={itemLinkReport.rows}
                        size="small"
                        paginator
                        rows={10}
                        rowsPerPageOptions={[10, 25, 50, 100]}
                        paginatorTemplate="FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink CurrentPageReport RowsPerPageDropdown"
                        currentPageReportTemplate="{first}-{last} of {totalRecords}"
                      >
                        <Column
                          field="itemNo"
                          header="Item"
                          style={{ width: 70 }}
                          body={(row) => formatBomItemNo(row)}
                        />
                        <Column
                          field="description"
                          header="Description"
                          body={(row) => formatBomDescription(row)}
                        />
                        <Column field="plQty" header="PL qty" style={{ width: 70 }} />
                        <Column
                          field="extractedQty"
                          header={
                            <span title="Quantity summed from GA balloon / callout extraction">
                              GA qty
                            </span>
                          }
                          style={{ width: 70 }}
                        />
                        <Column
                          header="Match"
                          style={{ width: 110 }}
                          body={(row) => {
                            if (row.qtyMatch === true) {
                              return (
                                <Tag
                                  className="rca-bom-match-tag"
                                  value="Match"
                                  severity="success"
                                  icon="pi pi-check-circle"
                                />
                              );
                            }
                            if (row.qtyMatch === false) {
                              return (
                                <Tag
                                  className="rca-bom-match-tag"
                                  value="Mismatch"
                                  severity="danger"
                                  icon="pi pi-times-circle"
                                />
                              );
                            }
                            return (
                              <Tag
                                value={row.status || "—"}
                                severity={
                                  String(row.status || "").toLowerCase().includes("only")
                                    ? "warning"
                                    : "secondary"
                                }
                              />
                            );
                          }}
                        />
                      </DataTable>
                    </div>
                  )}
                  {refDocsFound.length > 0 && (
                    <div className="mb-3">
                      <h4 style={{ marginBottom: "0.5rem" }}>Documents / refs</h4>
                      <p className="rca-section-note" style={{ marginBottom: "0.5rem" }}>
                        Reference sheets mentioned in notes or operations (only when uploaded).
                      </p>
                      <DataTable value={refDocsFound} size="small" paginator={false}>
                        <Column field="code" header="Code" style={{ width: "6rem" }} />
                        <Column
                          field="folderName"
                          header="Folder"
                          style={{ width: "8rem" }}
                          body={(row) => row.folderName || row.folderCode || "—"}
                        />
                        <Column field="name" header="File" />
                        <Column
                          header=""
                          style={{ width: "7rem" }}
                          body={(row) => (
                            <div className="flex gap-1">
                              <Button
                                type="button"
                                icon="pi pi-eye"
                                rounded
                                text
                                size="small"
                                aria-label={`Open ${row.code}`}
                                onClick={() => openRefDoc(row)}
                              />
                              <Button
                                type="button"
                                icon="pi pi-download"
                                rounded
                                text
                                size="small"
                                aria-label={`Download ${row.code}`}
                                onClick={() => downloadRefDoc(row)}
                              />
                            </div>
                          )}
                        />
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
                        label={shareToIedLabel}
                        icon="pi pi-send"
                        size="small"
                        onClick={shareToIed}
                        title={
                          sessionPlant
                            ? `Plant ${sessionPlant} → ${shareIedSbu || "?"} IED`
                            : shareToIedLabel
                        }
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
        {priorDialog.matches?.[0] ? (
          <div className="rca-prior-latest" style={{ fontSize: "0.8rem" }}>
            <button
              type="button"
              className="p-link"
              style={{ fontSize: "0.8rem" }}
              onClick={() => {
                const sid = priorDialog.matches[0].sessionId;
                setPriorDialog((s) => ({ ...s, visible: false }));
                if (sid) openSessionById(sid);
              }}
            >
              Session {priorDialog.matches[0].sessionId}
              {priorDialog.matches[0].partNumber
                ? ` · ${priorDialog.matches[0].partNumber}`
                : ""}
              {priorDialog.matches[0].matchedFilenames?.length
                ? ` · ${priorDialog.matches[0].matchedFilenames[0]}`
                : ""}
              {priorDialog.matches[0].routeStatus
                ? ` · ${priorDialog.matches[0].routeStatus}`
                : ""}
            </button>
          </div>
        ) : null}
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
            label:
              p.label ||
              (p.sbuName
                ? `${p.code} - ${p.sbuName}`
                : p.code),
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
          setViewPopoverCrop(null);
          viewPopoverRef.current?.hide?.();
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
                setViewPopoverCrop(null);
                viewPopoverRef.current?.hide?.();
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
          Operator instructions. Click the text to edit. Item names appear in preview only.
        </p>
        <InstructionClickEdit
          value={instrDialog.draft}
          onChange={(e) => setInstrDialog((s) => ({ ...s, draft: e.target.value }))}
          onSave={saveSuggestedInstruction}
          itemLookup={plItemLookup}
          viewCrops={tableCrops}
          onOpenViewCrop={(crop, el) => {
            setViewPopoverCrop(crop);
            const ev = { currentTarget: el, target: el };
            viewPopoverRef.current?.toggle?.(ev);
          }}
          foundByCode={refDocsByCode}
          onOpenRefDoc={openRefDoc}
          resetKey={`${instrDialog.visible}:${instrDialog.opKey || ""}`}
          rows={6}
        />
        {tableCropsLoading ? (
          <p className="oarc-instr-dialog__hint" style={{ marginTop: "0.5rem" }}>
            Checking drawing for referenced view snapshot…
          </p>
        ) : null}
        <OverlayPanel
          ref={viewPopoverRef}
          className="instr-view-popover"
          dismissable
          showCloseIcon={false}
          onHide={() => setViewPopoverCrop(null)}
        >
          {viewPopoverCrop?.src ? (
            <>
              <div className="instr-view-popover__head">
                <i className="pi pi-image" aria-hidden />
                <span className="instr-view-popover__head-title">
                  {viewPopoverCrop.label || "Drawing view"}
                </span>
                <Button
                  type="button"
                  icon="pi pi-window-maximize"
                  rounded
                  text
                  size="small"
                  aria-label="View full size"
                  onClick={() => {
                    setTableCropView({
                      label: viewPopoverCrop.label,
                      src: viewPopoverCrop.src,
                      filename: viewPopoverCrop.filename,
                      page: viewPopoverCrop.page,
                      confidence: viewPopoverCrop.confidence,
                    });
                    viewPopoverRef.current?.hide?.();
                  }}
                />
                <Button
                  type="button"
                  icon="pi pi-times"
                  rounded
                  text
                  size="small"
                  aria-label="Close"
                  onClick={() => viewPopoverRef.current?.hide?.()}
                />
              </div>
              <div className="instr-view-popover__body">
                <img
                  src={viewPopoverCrop.src}
                  alt={viewPopoverCrop.label || "Drawing view crop"}
                  className="instr-view-popover__img"
                />
              </div>
              <div className="instr-view-popover__foot">
                <span className="instr-view-popover__pager">
                  {(() => {
                    const idx = Math.max(
                      0,
                      tableCrops.findIndex(
                        (c) =>
                          c === viewPopoverCrop ||
                          (c.kind === viewPopoverCrop.kind &&
                            String(c.refId || "") === String(viewPopoverCrop.refId || "") &&
                            c.src === viewPopoverCrop.src)
                      )
                    );
                    const n = tableCrops.length || 1;
                    return (
                      <>
                        <Button
                          type="button"
                          icon="pi pi-chevron-left"
                          rounded
                          text
                          size="small"
                          disabled={n <= 1}
                          aria-label="Previous view"
                          onClick={() => {
                            if (n <= 1) return;
                            const next = tableCrops[(idx - 1 + n) % n];
                            setViewPopoverCrop(next);
                          }}
                        />
                        <span>
                          {idx + 1} / {n}
                        </span>
                        <Button
                          type="button"
                          icon="pi pi-chevron-right"
                          rounded
                          text
                          size="small"
                          disabled={n <= 1}
                          aria-label="Next view"
                          onClick={() => {
                            if (n <= 1) return;
                            const next = tableCrops[(idx + 1) % n];
                            setViewPopoverCrop(next);
                          }}
                        />
                      </>
                    );
                  })()}
                </span>
                <Button
                  type="button"
                  label="View full size"
                  icon="pi pi-external-link"
                  link
                  size="small"
                  className="p-0"
                  onClick={() => {
                    setTableCropView({
                      label: viewPopoverCrop.label,
                      src: viewPopoverCrop.src,
                      filename: viewPopoverCrop.filename,
                      page: viewPopoverCrop.page,
                      confidence: viewPopoverCrop.confidence,
                    });
                    viewPopoverRef.current?.hide?.();
                  }}
                />
              </div>
            </>
          ) : (
            <p className="oarc-instr-dialog__hint" style={{ padding: "0.75rem" }}>
              No snapshot available.
            </p>
          )}
        </OverlayPanel>
        {(instrDialog.itemsUsed || []).length > 0 ? (
          <div className="oarc-instr-dialog__meta" aria-label="Items from Parts List">
            <span className="oarc-instr-dialog__meta-label">Items</span>
            <div className="oarc-instr-dialog__chips">
              {(instrDialog.itemsUsed || []).map((item, idx) => {
                const chip = formatItemChip(item, plItemLookup);
                return (
                  <span
                    key={`${item.itemNo}-${idx}`}
                    className="oarc-instr-chip oarc-instr-chip--item"
                    title={chip}
                  >
                    {chip}
                  </span>
                );
              })}
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
            : "Drawing view"
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
              alt={tableCropView.label || "Drawing view crop"}
              className="rca-table-crop__img"
            />
            <p className="oarc-instr-dialog__hint" style={{ marginTop: "0.5rem" }}>
              Snapshot from the uploaded drawing. Shown only when the caption was located with high
              confidence (never invented).
            </p>
          </div>
        ) : null}
      </Dialog>

      <Dialog
        header={`OP ${editRow?.opNo ?? ""} details`}
        visible={editVisible}
        onHide={() => setEditVisible(false)}
        style={{ width: "min(92vw, 36rem)" }}
        className="rca-edit-dialog"
        footer={
          <div className="flex justify-content-end gap-2">
            <Button type="button" label="Cancel" outlined size="small" onClick={() => setEditVisible(false)} />
            <Button
              type="button"
              label="Save"
              icon="pi pi-check"
              size="small"
              disabled={opsReadOnly || iedFieldsOnly}
              onClick={saveDetails}
            />
          </div>
        }
      >
        {editRow && (
          <div className="grid formgrid p-fluid">
            <p className="col-12 rca-section-note" style={{ marginBottom: "0.35rem" }}>
              {editRow.operation || "Untitled operation"}
              {editRow.workCentre ? ` · ${editRow.workCentre}` : ""}
            </p>
            {[
              ["tool", "Tool"],
              ["items", "Items"],
              ["torqueSpec", "Torque"],
              ["reference", "Reference"],
              ["inspection", "Inspection"],
            ].map(([key, label]) => (
              <div className="field col-12 md:col-6" key={key}>
                <label htmlFor={`rca-${key}`}>{label}</label>
                <SafeInputText
                  profile="text"
                  id={`rca-${key}`}
                  value={editRow[key] ?? ""}
                  disabled={opsReadOnly || iedFieldsOnly}
                  onChange={(e) => setEditRow((r) => ({ ...r, [key]: e.target.value }))}
                />
              </div>
            ))}
          </div>
        )}
      </Dialog>
      <Dialog
        header={refDocPreview?.title || "Reference sheet"}
        visible={Boolean(refDocPreview?.url)}
        style={{ width: "min(96vw, 56rem)" }}
        modal
        dismissableMask
        onHide={() => {
          if (refDocPreview?.url) URL.revokeObjectURL(refDocPreview.url);
          setRefDocPreview(null);
        }}
        footer={
          <div className="flex justify-content-end gap-2">
            <Button
              type="button"
              label="Download"
              icon="pi pi-download"
              size="small"
              outlined
              disabled={!refDocPreview?.documentId}
              onClick={() =>
                downloadRefDoc({
                  documentId: refDocPreview.documentId,
                  name: refDocPreview.filename,
                  code: refDocPreview.title,
                })
              }
            />
            <Button
              type="button"
              label="Close"
              size="small"
              onClick={() => {
                if (refDocPreview?.url) URL.revokeObjectURL(refDocPreview.url);
                setRefDocPreview(null);
              }}
            />
          </div>
        }
      >
        {refDocPreview?.url ? (
          <object
            data={refDocPreview.url}
            type="application/pdf"
            className="rc-refdocs__preview-frame"
            aria-label={refDocPreview.title}
          >
            <a href={refDocPreview.url} download={refDocPreview.filename || "sheet.pdf"}>
              Download PDF
            </a>
          </object>
        ) : null}
      </Dialog>

      <PmfAnalyzeLoader
        visible={analyzing}
        message={analyzeStatus.message || "Analyzing…"}
        detail={analyzeStatus.detail || ""}
        progress={analyzeStatus.progress || 0}
        onCancel={() => stopAnalysis()}
      />
    </AppShell>
  );
}
