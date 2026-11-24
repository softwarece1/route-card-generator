import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Calendar } from "primereact/calendar";
import { Dialog } from "primereact/dialog";
import { Dropdown } from "primereact/dropdown";
import { Message } from "primereact/message";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import OarcPreviewDialog from "@/components/OarcPreviewDialog";
import RouteRemarksPanel from "@/components/RouteRemarksPanel";
import TableComponent, {
  TableActions,
  TableFileChip,
  TablePrimarySub,
  TableStatusBadge,
} from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { mapPayloadToOrderPrefill } from "@/lib/pmfOrderPrefill";
import { printOarcPdf } from "@/lib/oarcPrint";
import {
  ROUTE_STATUS_FILTER_OPTIONS,
  displayStatusLabel,
  displayStatusTone,
  routeStatusLabel,
} from "@/lib/routeStatus";
import { fetchSbus } from "@/services/authApi";
import { useNavigate } from "react-router-dom";
import {
  // batchEnqueueAnalyze, // Analyze selected — commented out in UI
  cloneRouteToSession,
  compareRouteCards,
  createSession,
  fetchAdminExtractions,
  fetchAdminExtractionDetail,
  fetchAdminUsers,
  fetchDeptUsers,
  fetchMyExtractionDetail,
  fetchMyExtractions,
  sessionDocumentFileUrl,
} from "@/services/routeCardApi";
import { toast } from "@/lib/toast";
import "./route-card-generation-alt.scss";
import "./extractions.scss";

function docsFromDetail(detail) {
  const byRole = {};
  for (const d of detail?.documents || []) {
    byRole[d.role] = {
      id: d.id,
      name: d.filename,
      type: d.fileType,
      sizeLabel: d.sizeLabel,
      role: d.role,
    };
  }
  return {
    drawing: byRole.drawing || null,
    partslist: byRole.partslist || null,
    wirelist: byRole.wirelist || null,
  };
}

function toYmd(d) {
  if (!d) return undefined;
  const dt = d instanceof Date ? d : new Date(d);
  if (Number.isNaN(dt.getTime())) return undefined;
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const day = String(dt.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function startOfLocalDay(d) {
  const dt = d instanceof Date ? new Date(d) : new Date(d);
  if (Number.isNaN(dt.getTime())) return null;
  dt.setHours(0, 0, 0, 0);
  return dt;
}

/** Default range: 1st of current month → today (local). */
function defaultDateRange() {
  const today = startOfLocalDay(new Date());
  const from = new Date(today.getFullYear(), today.getMonth(), 1);
  return { fromDate: from, toDate: today };
}

function defaultFilters() {
  return {
    empId: null,
    sbu: null,
    status: null,
    ...defaultDateRange(),
  };
}

const STATUS_OPTIONS = ROUTE_STATUS_FILTER_OPTIONS;

function filtersAreActive(f) {
  const d = defaultFilters();
  return Boolean(
    f?.empId ||
      f?.sbu ||
      f?.status ||
      toYmd(f?.fromDate) !== toYmd(d.fromDate) ||
      toYmd(f?.toDate) !== toYmd(d.toDate)
  );
}

function rowUpdatedDate(row) {
  const raw = row?.updatedAt || row?.createdAt;
  if (!raw) return null;
  return startOfLocalDay(raw);
}

export default function ExtractionsPage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";
  const isIed = user?.role === "ied";
  const isSbuHead = user?.role === "sbu_head";
  const [items, setItems] = useState([]);
  const [users, setUsers] = useState([]);
  const [sbus, setSbus] = useState([]);
  const [filters, setFilters] = useState(() => defaultFilters());
  const [applied, setApplied] = useState(() => defaultFilters());
  const [iedTab, setIedTab] = useState(0); // 0 Pending, 1 Approved
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [oarcOpen, setOarcOpen] = useState(false);
  const [oarcMode, setOarcMode] = useState("preview");
  const [oarcSessionId, setOarcSessionId] = useState(null);
  const [oarcPayload, setOarcPayload] = useState(null);
  const [oarcDocs, setOarcDocs] = useState({});
  const [selected, setSelected] = useState([]);
  const [compareResult, setCompareResult] = useState(null);
  const navigate = useNavigate();

  const sbuOptions = useMemo(() => {
    const fromMaster = sbus.map((d) => ({
      label: d.label || d.name,
      value: d.value || d.name,
    }));
    const fromUsers = users
      .map((u) => (u.sbu || "").trim())
      .filter(Boolean);
    const merged = new Map();
    for (const opt of fromMaster) merged.set(opt.value, opt);
    for (const name of fromUsers) {
      if (!merged.has(name)) merged.set(name, { label: name, value: name });
    }
    return [{ label: "All SBUs", value: null }, ...merged.values()];
  }, [sbus, users]);

  /** Employees for the selected SBU (admin) or caller's SBU reports (SBU head). */
  const empOptions = useMemo(() => {
    const sbu = (filters.sbu || "").trim();
    let pool = users;
    if (isAdmin && sbu) {
      pool = users.filter((u) => (u.sbu || "").trim() === sbu);
    }
    return [
      { label: "All employees", value: null },
      ...pool.map((u) => ({
        label: `${u.empId} — ${u.name}${u.sbu ? ` (${u.sbu})` : ""}`,
        value: u.empId,
      })),
    ];
  }, [users, filters.sbu, isAdmin]);

  const loadMeta = useCallback(async () => {
    if (isIed) return;
    try {
      if (isAdmin) {
        const [uRes, dRows] = await Promise.all([
          fetchAdminUsers(),
          fetchSbus().catch(() => []),
        ]);
        setUsers(uRes.users || []);
        setSbus(Array.isArray(dRows) ? dRows : []);
      } else if (isSbuHead) {
        const uRes = await fetchDeptUsers();
        setUsers(uRes.users || []);
        setSbus([]);
      }
    } catch (err) {
      setError(err.message || "Failed to load filter options");
    }
  }, [isAdmin, isSbuHead, isIed]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (isAdmin) {
        const eRes = await fetchAdminExtractions({
          empId: applied.empId || undefined,
          dept: applied.sbu || undefined,
          status: applied.status || undefined,
          fromDate: toYmd(applied.fromDate),
          toDate: toYmd(applied.toDate),
        });
        setItems(eRes.items || []);
      } else {
        const res = await fetchMyExtractions();
        setItems(res.items || []);
      }
    } catch (err) {
      setError(err.message || "Failed to load history");
    } finally {
      setLoading(false);
    }
  }, [applied, isAdmin]);

  useEffect(() => {
    loadMeta();
  }, [loadMeta]);

  useEffect(() => {
    load();
  }, [load]);

  const applyFilters = () => setApplied({ ...filters });

  const clearFilters = () => {
    const next = defaultFilters();
    setFilters(next);
    setApplied(next);
  };

  const hasAppliedFilters = filtersAreActive(applied);
  const canCompare = (selected || []).length === 2;

  const openIedReview = async (row) => {
    try {
      const data = await loadDetail(row.sessionId);
      if (!data?.payload) {
        setError("No route data for IED review yet.");
        return;
      }
      setOarcPayload(data.payload);
      setOarcDocs(docsFromDetail(data));
      setOarcSessionId(row.sessionId);
      setOarcMode("ied");
      setOarcOpen(true);
      setDetail(data);
    } catch (err) {
      setError(err.message || "Could not open IED review");
    }
  };

  const loadDetail = async (sessionId) => {
    setDetailLoading(true);
    try {
      const data = isAdmin
        ? await fetchAdminExtractionDetail(sessionId)
        : await fetchMyExtractionDetail(sessionId);
      return data;
    } finally {
      setDetailLoading(false);
    }
  };

  const openDetail = async (row) => {
    try {
      const data = await loadDetail(row.sessionId);
      setDetail(data);
      setDetailOpen(true);
    } catch (err) {
      setError(err.message || "Could not open detail");
    }
  };

  const openOarc = async (rowOrDetail) => {
    try {
      const data =
        rowOrDetail?.payload != null
          ? rowOrDetail
          : await loadDetail(rowOrDetail.sessionId);
      if (!data?.payload) {
        setError("No extracted OARC data for this session yet. Analyze it first.");
        return;
      }
      setOarcPayload(data.payload);
      setOarcDocs(docsFromDetail(data));
      setOarcSessionId(data.sessionId || rowOrDetail.sessionId || null);
      setOarcMode("preview");
      setOarcOpen(true);
      setDetail(data);
    } catch (err) {
      setError(err.message || "Could not open OARC preview");
    }
  };

  const printOarc = async (rowOrDetail) => {
    try {
      const data =
        rowOrDetail?.payload != null
          ? rowOrDetail
          : await loadDetail(rowOrDetail.sessionId);
      if (!data?.payload) {
        setError("No extracted OARC data to print for this session.");
        return;
      }
      const docs = docsFromDetail(data);
      const mapped = mapPayloadToOrderPrefill(data.payload, { requiredQty: 1 });
      printOarcPdf(
        {
          ...mapped.header,
          production_order: "",
          sale_order: "",
          wbs_element: "",
          plant_id: "",
          total_operations: mapped.operations.length || 0,
        },
        mapped.operations,
        mapped.rawMaterials,
        {
          drawing: docs.drawing
            ? { fileName: docs.drawing.name, version: "v1" }
            : null,
          partList: docs.partslist
            ? { fileName: docs.partslist.name, version: "v1" }
            : null,
        },
      );
    } catch (err) {
      setError(err.message || "Could not print OARC");
    }
  };

  const downloadDoc = (sessionId, role, filename) => {
    const url = sessionDocumentFileUrl(sessionId, role);
    fetch(url, { credentials: "include" })
      .then((r) => {
        if (!r.ok) throw new Error("Download failed");
        return r.blob();
      })
      .then((blob) => {
        const href = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = href;
        a.download = filename || `${role}.bin`;
        a.click();
        URL.revokeObjectURL(href);
      })
      .catch((err) => setError(err.message || "Download failed"));
  };

  const hasPayload = (row) =>
    row.status === "analyzed" || row.status === "approved" || row.routeCardId;

  const patchFilter = (key, value) =>
    setFilters((prev) => {
      const next = { ...prev, [key]: value };
      // Changing SBU clears employee if they are outside that SBU
      if (key === "sbu" && prev.empId) {
        const sbu = (value || "").trim();
        if (sbu) {
          const stillOk = users.some(
            (u) => u.empId === prev.empId && (u.sbu || "").trim() === sbu
          );
          if (!stillOk) next.empId = null;
        }
      }
      return next;
    });

  const displayedItems = useMemo(() => {
    let rows = items;
    if (isIed) {
      return rows.filter((row) => {
        const st = String(row.routeStatus || "").toLowerCase();
        if (iedTab === 0) return st === "ied_review";
        return st === "ied_complete" || st === "approved";
      });
    }

    // Non-admin: apply status / emp / date client-side (admin uses API params)
    if (!isAdmin) {
      if (applied.status) {
        const st = String(applied.status).toLowerCase();
        const routeStatuses = new Set([
          "draft",
          "ied_review",
          "ied_complete",
          "approved",
        ]);
        rows = rows.filter((row) => {
          if (routeStatuses.has(st)) {
            return String(row.routeStatus || "").toLowerCase() === st;
          }
          return String(row.status || "").toLowerCase() === st;
        });
      }
      if (applied.empId) {
        const want = String(applied.empId);
        rows = rows.filter(
          (row) => String(row.user?.empId || "") === want
        );
      }
      const from = startOfLocalDay(applied.fromDate);
      const to = startOfLocalDay(applied.toDate);
      if (from || to) {
        rows = rows.filter((row) => {
          const updated = rowUpdatedDate(row);
          if (!updated) return false;
          if (from && updated < from) return false;
          if (to && updated > to) return false;
          return true;
        });
      }
    }
    return rows;
  }, [items, applied, isAdmin, isIed, iedTab]);

  return (
    <AppShell active="history">
        <div className="rc-hist">
          <PageHeader
            title={
              isAdmin
                ? "All extractions"
                : isIed
                  ? "IED review queue"
                  : isSbuHead
                    ? "Extractions & approvals"
                    : "My extractions"
            }
            subtitle={
              isAdmin
                ? "Browse every user’s analyzed sessions, open OARC preview, or print PDF."
                : isIed
                  ? "Shared route cards for your SBU — set setup / per-piece time (in hrs), then complete IED review."
                  : isSbuHead
                    ? "Your extractions plus cards awaiting approval after IED."
                    : "Your past analyses — share to IED, then approve after IED completes."
            }
            icon="pi pi-history"
            actions={
              <Button
                type="button"
                label="Refresh"
                icon="pi pi-refresh"
                size="small"
                outlined
                onClick={() => load()}
              />
            }
          />
          {error ? <Message severity="error" text={error} className="w-full mb-3" /> : null}

          {!isIed && canCompare ? (
          <div className="flex gap-2 flex-wrap mb-3">
            <Button
              type="button"
              label="Compare selected (2)"
              icon="pi pi-arrows-h"
              outlined
              size="small"
              className="p-button-sm"
              onClick={async () => {
                const [a, b] = selected;
                try {
                  const res = await compareRouteCards(a.routeCardId, b.routeCardId);
                  setCompareResult({
                    ...res,
                    metaA: {
                      partNumber: a.partNumber || a.drawingNumber || "",
                      sessionId: a.sessionId,
                      status: a.status,
                    },
                    metaB: {
                      partNumber: b.partNumber || b.drawingNumber || "",
                      sessionId: b.sessionId,
                      status: b.status,
                    },
                  });
                } catch (e) {
                  toast.error(e.message || "Compare failed");
                }
              }}
            />
          </div>
          ) : null}
          {compareResult && (
            <Dialog
              header="Route compare"
              visible={!!compareResult}
              onHide={() => setCompareResult(null)}
              style={{ width: "min(96vw, 56rem)" }}
              className="rc-compare-dialog"
            >
              <div className="rc-compare">
                <div className="rc-compare__heads">
                  <div className="rc-compare__card rc-compare__card--a">
                    <span className="rc-compare__badge">Order A</span>
                    <strong>
                      {compareResult.metaA?.partNumber || `Route #${compareResult.a?.id}`}
                    </strong>
                    <span>
                      Session {compareResult.metaA?.sessionId ?? "—"} ·{" "}
                      {compareResult.a?.opCount ?? 0} ops · {compareResult.a?.status || "—"}
                    </span>
                  </div>
                  <div className="rc-compare__vs">vs</div>
                  <div className="rc-compare__card rc-compare__card--b">
                    <span className="rc-compare__badge">Order B</span>
                    <strong>
                      {compareResult.metaB?.partNumber || `Route #${compareResult.b?.id}`}
                    </strong>
                    <span>
                      Session {compareResult.metaB?.sessionId ?? "—"} ·{" "}
                      {compareResult.b?.opCount ?? 0} ops · {compareResult.b?.status || "—"}
                    </span>
                  </div>
                </div>

                <div className="rc-compare__stats">
                  <div className="rc-compare__stat rc-compare__stat--added">
                    <strong>{(compareResult.added || []).length}</strong>
                    <span>Only in B (added)</span>
                  </div>
                  <div className="rc-compare__stat rc-compare__stat--removed">
                    <strong>{(compareResult.removed || []).length}</strong>
                    <span>Only in A (removed)</span>
                  </div>
                  <div className="rc-compare__stat rc-compare__stat--changed">
                    <strong>{(compareResult.changed || []).length}</strong>
                    <span>Changed</span>
                  </div>
                </div>

                {(compareResult.added || []).length > 0 && (
                  <section className="rc-compare__section rc-compare__section--added">
                    <h4>In Order B only</h4>
                    <ul>
                      {(compareResult.added || []).map((op, i) => (
                        <li key={`add-${i}`}>
                          <span className="rc-compare__opno">OP {op.opNo}</span>
                          <span className="rc-compare__opname">{op.operation || "—"}</span>
                          <span className="rc-compare__meta">
                            {[op.workCentre, op.machine, op.tool].filter(Boolean).join(" · ") || "—"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {(compareResult.removed || []).length > 0 && (
                  <section className="rc-compare__section rc-compare__section--removed">
                    <h4>In Order A only</h4>
                    <ul>
                      {(compareResult.removed || []).map((op, i) => (
                        <li key={`rem-${i}`}>
                          <span className="rc-compare__opno">OP {op.opNo}</span>
                          <span className="rc-compare__opname">{op.operation || "—"}</span>
                          <span className="rc-compare__meta">
                            {[op.workCentre, op.machine, op.tool].filter(Boolean).join(" · ") || "—"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {(compareResult.changed || []).length > 0 && (
                  <section className="rc-compare__section rc-compare__section--changed">
                    <h4>Changed steps</h4>
                    <ul>
                      {(compareResult.changed || []).map((row, i) => (
                        <li key={`chg-${i}`} className="rc-compare__changed-row">
                          <div>
                            <span className="rc-compare__side">A</span>
                            OP {row.before?.opNo}: {row.before?.operation} · {row.before?.workCentre}
                          </div>
                          <div>
                            <span className="rc-compare__side">B</span>
                            OP {row.after?.opNo}: {row.after?.operation} · {row.after?.workCentre}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {(compareResult.added || []).length === 0 &&
                (compareResult.removed || []).length === 0 &&
                (compareResult.changed || []).length === 0 ? (
                  <p className="rc-compare__same">These two routes look the same.</p>
                ) : null}
              </div>
            </Dialog>
          )}

          {isIed ? (
            <div className="flex gap-2 mb-3">
              <Button
                type="button"
                label="Pending"
                size="small"
                outlined={iedTab !== 0}
                onClick={() => setIedTab(0)}
              />
              <Button
                type="button"
                label="Approved"
                size="small"
                outlined={iedTab !== 1}
                onClick={() => setIedTab(1)}
              />
            </div>
          ) : null}

          {!isIed ? (
            <div className="rc-hist__filters">
              <div className="rc-hist__filter">
                <label htmlFor="fromDate">From date</label>
                <Calendar
                  inputId="fromDate"
                  value={filters.fromDate}
                  onChange={(e) => patchFilter("fromDate", e.value)}
                  dateFormat="dd/mm/yy"
                  placeholder="Start date"
                  showIcon
                  showButtonBar
                  maxDate={filters.toDate || undefined}
                  className="w-full"
                />
              </div>
              <div className="rc-hist__filter">
                <label htmlFor="toDate">To date</label>
                <Calendar
                  inputId="toDate"
                  value={filters.toDate}
                  onChange={(e) => patchFilter("toDate", e.value)}
                  dateFormat="dd/mm/yy"
                  placeholder="End date"
                  showIcon
                  showButtonBar
                  minDate={filters.fromDate || undefined}
                  className="w-full"
                />
              </div>
              {isAdmin ? (
                <div className="rc-hist__filter">
                  <label htmlFor="sbuFilter">SBU</label>
                  <Dropdown
                    inputId="sbuFilter"
                    value={filters.sbu}
                    options={sbuOptions}
                    onChange={(e) => patchFilter("sbu", e.value)}
                    className="w-full"
                    placeholder="All SBUs"
                    filter
                    showClear
                  />
                </div>
              ) : null}
              {isAdmin || isSbuHead ? (
                <div className="rc-hist__filter">
                  <label htmlFor="empFilter">Employee</label>
                  <Dropdown
                    inputId="empFilter"
                    value={filters.empId}
                    options={empOptions}
                    onChange={(e) => patchFilter("empId", e.value)}
                    className="w-full"
                    placeholder="All employees"
                    filter
                    showClear
                  />
                </div>
              ) : null}
              <div className="rc-hist__filter">
                <label htmlFor="statusFilter">Status</label>
                <Dropdown
                  inputId="statusFilter"
                  value={filters.status}
                  options={STATUS_OPTIONS}
                  onChange={(e) => patchFilter("status", e.value)}
                  className="w-full"
                  placeholder="All statuses"
                  showClear
                />
              </div>
              <div className="rc-hist__filter-actions">
                <Button
                  type="button"
                  label="Apply"
                  icon="pi pi-filter"
                  size="small"
                  className="p-button-sm"
                  onClick={applyFilters}
                />
                {hasAppliedFilters ? (
                  <Button
                    type="button"
                    label="Clear"
                    icon="pi pi-times"
                    size="small"
                    className="p-button-sm"
                    outlined
                    severity="secondary"
                    onClick={clearFilters}
                  />
                ) : null}
              </div>
            </div>
          ) : null}

          <TableComponent
            value={displayedItems}
            loading={loading || detailLoading}
            paginator
            rows={10}
            emptyMessage={
              isIed
                ? iedTab === 0
                  ? "No cards awaiting IED review in your SBU."
                  : "No completed / approved IED reviews yet."
                : "No extractions yet."
            }
            dataKey="sessionId"
            selectionMode={isIed ? undefined : "multiple"}
            selection={isIed ? undefined : selected}
            onSelectionChange={isIed ? undefined : (e) => setSelected(e.value || [])}
            columns={[
              { type: "index", header: "#", style: { width: "3.25rem" } },
              {
                header: "Session",
                sortable: true,
                field: "sessionId",
                style: { width: "6.5rem" },
              },
              ...(isAdmin
                ? [
                    {
                      header: "Employee",
                      body: (row) =>
                        row.user ? (
                          <TablePrimarySub
                            primary={row.user.empId}
                            secondary={[row.user.name, row.user.sbu].filter(Boolean).join(" · ")}
                          />
                        ) : (
                          "—"
                        ),
                    },
                  ]
                : []),
              { field: "partNumber", header: "Part No.", sortable: true },
              { field: "partName", header: "Part Name", sortable: true },
              {
                header: "Status",
                sortable: true,
                field: "routeStatus",
                body: (row) => (
                  <TableStatusBadge
                    value={displayStatusLabel(row)}
                    tone={displayStatusTone(row)}
                  />
                ),
              },
              {
                field: "operationCount",
                header: "Ops",
                sortable: true,
                style: { width: "5rem" },
              },
              ...(isIed
                ? [
                    {
                      header: "Shared by",
                      body: (row) =>
                        row.user ? (
                          <TablePrimarySub
                            primary={row.user.empId}
                            secondary={[row.user.name, row.user.sbu]
                              .filter(Boolean)
                              .join(" · ")}
                          />
                        ) : (
                          "—"
                        ),
                    },
                  ]
                : [
                    {
                      header: "Files",
                      body: (row) => (
                        <TableFileChip
                          label={(row.documents || []).map((d) => d.role).join(", ") || ""}
                        />
                      ),
                    },
                  ]),
              {
                header: "Updated",
                sortable: true,
                field: "updatedAt",
                body: (row) =>
                  row.updatedAt ? new Date(row.updatedAt).toLocaleString() : "—",
              },
              {
                header: "Actions",
                style: { width: isIed ? "7rem" : "9rem" },
                body: (row) => (
                  <TableActions>
                    {isIed ? (
                      <Button
                        type="button"
                        icon="pi pi-pencil"
                        rounded
                        text
                        size="small"
                        tooltip={
                          row.routeStatus === "ied_review"
                            ? "Review & set standards"
                            : "View IED review"
                        }
                        tooltipOptions={{ position: "top" }}
                        disabled={!row.routeCardId}
                        onClick={() => openIedReview(row)}
                      />
                    ) : (
                      <>
                        <Button
                          type="button"
                          icon="pi pi-eye"
                          rounded
                          text
                          size="small"
                          tooltip="View OARC"
                          tooltipOptions={{ position: "top" }}
                          disabled={!hasPayload(row)}
                          onClick={() => openOarc(row)}
                        />
                        <Button
                          type="button"
                          icon="pi pi-print"
                          rounded
                          text
                          size="small"
                          tooltip="Print OARC PDF"
                          tooltipOptions={{ position: "top" }}
                          disabled={!hasPayload(row)}
                          onClick={() => printOarc(row)}
                        />
                        <Button
                          type="button"
                          icon="pi pi-ellipsis-v"
                          rounded
                          text
                          size="small"
                          tooltip="Session & files"
                          tooltipOptions={{ position: "top" }}
                          onClick={() => openDetail(row)}
                        />
                      </>
                    )}
                  </TableActions>
                ),
              },
            ]}
          />
        </div>

      <Dialog
        header={detail ? `Session ${detail.sessionId}` : "Extraction"}
        visible={detailOpen}
        onHide={() => setDetailOpen(false)}
        style={{ width: "min(92vw, 42rem)" }}
        className="rc-hist-dialog"
        footer={
          detail?.payload ? (
            <div className="flex justify-content-end gap-2">
              <Button
                type="button"
                label="View OARC"
                icon="pi pi-eye"
                outlined
                size="small"
                onClick={() => {
                  setDetailOpen(false);
                  openOarc(detail);
                }}
              />
              <Button
                type="button"
                label="Print PDF"
                icon="pi pi-print"
                size="small"
                onClick={() => printOarc(detail)}
              />
              <Button
                type="button"
                label="Clone route to new session"
                icon="pi pi-copy"
                outlined
                size="small"
                disabled={!detail?.routeCardId && !detail?.payload?.id}
                onClick={async () => {
                  try {
                    const sess = await createSession();
                    const fromId = detail.routeCardId || detail.payload?.id;
                    await cloneRouteToSession(sess.id || sess.sessionId, fromId);
                    toast.success("Cloned into new session — open Generator");
                    navigate(`/generator?sessionId=${sess.id || sess.sessionId}`);
                  } catch (e) {
                    toast.error(e.message || "Clone failed");
                  }
                }}
              />
            </div>
          ) : null
        }
      >
        {detail ? (
          <div className="rc-hist-detail">
            <dl>
              <div>
                <dt>Part</dt>
                <dd>
                  {detail.partNumber || "—"} {detail.partName ? `· ${detail.partName}` : ""}
                </dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{displayStatusLabel(detail)}</dd>
              </div>
              {detail.user ? (
                <div>
                  <dt>User</dt>
                  <dd>
                    {detail.user.empId} — {detail.user.name}
                    {detail.user.sbu ? ` (${detail.user.sbu})` : ""}
                  </dd>
                </div>
              ) : null}
              <div>
                <dt>Route card</dt>
                <dd>
                  {detail.routeCardId
                    ? `#${detail.routeCardId} (${detail.routeStatus || "—"}) · ${detail.operationCount || 0} ops`
                    : "—"}
                </dd>
              </div>
              {detail.routeCardId ? (
                <div>
                  <dt>Remarks</dt>
                  <dd>
                    <RouteRemarksPanel routeCardId={detail.routeCardId} compact />
                  </dd>
                </div>
              ) : null}
              {detail.payload?.drawingInfo ? (
                <div>
                  <dt>Drawing info</dt>
                  <dd className="rc-hist-detail__json">
                    {[
                      detail.payload.drawingInfo.material,
                      detail.payload.drawingInfo.overallDimensions,
                      detail.payload.drawingInfo.surfaceFinish,
                    ]
                      .filter(Boolean)
                      .join(" · ") || "Extracted title block available in OARC view"}
                  </dd>
                </div>
              ) : null}
            </dl>
            <h3>Stored files</h3>
            {(detail.documents || []).length === 0 ? (
              <p className="text-color-secondary">No files.</p>
            ) : (
              <ul className="rc-hist-files">
                {(detail.documents || []).map((d) => (
                  <li key={d.id || d.role}>
                    <span>
                      <TableStatusBadge value={d.role} tone="info" />{" "}
                      {d.filename} <small>({d.sizeLabel})</small>
                      <br />
                      <small className="text-color-secondary">
                        {d.storageBackend?.startsWith("minio") ? "MinIO" : "Local"} · {d.objectPath}
                      </small>
                    </span>
                    <Button
                      type="button"
                      icon="pi pi-download"
                      rounded
                      text
                      size="small"
                      aria-label={`Download ${d.role}`}
                      onClick={() => downloadDoc(detail.sessionId, d.role, d.filename)}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </Dialog>

      <OarcPreviewDialog
        visible={oarcOpen}
        onHide={() => setOarcOpen(false)}
        payload={oarcPayload}
        docs={oarcDocs}
        mode={oarcMode}
        sessionId={oarcSessionId}
        onSaved={(next) => {
          if (next) setOarcPayload(next);
          load();
        }}
        onCompleted={() => {
          setOarcOpen(false);
          load();
        }}
      />
    </AppShell>
  );
}
