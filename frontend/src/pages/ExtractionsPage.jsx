import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Calendar } from "primereact/calendar";
import { Dialog } from "primereact/dialog";
import { Dropdown } from "primereact/dropdown";
import { Message } from "primereact/message";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import OarcPreviewDialog from "@/components/OarcPreviewDialog";
import TableComponent, {
  TableActions,
  TableFileChip,
  TablePrimarySub,
  TableStatusBadge,
} from "@/components/TableComponent";
import { getToken, getUser } from "@/lib/auth";
import { mapPayloadToOrderPrefill } from "@/lib/pmfOrderPrefill";
import { printOarcPdf } from "@/lib/oarcPrint";
import { fetchDepartments } from "@/services/authApi";
import { useNavigate } from "react-router-dom";
import {
  // batchEnqueueAnalyze, // Analyze selected — commented out in UI
  cloneRouteToSession,
  compareRouteCards,
  createSession,
  fetchAdminExtractions,
  fetchAdminExtractionDetail,
  fetchAdminUsers,
  fetchMyExtractionDetail,
  fetchMyExtractions,
  sessionDocumentFileUrl,
} from "@/services/routeCardApi";
import { toast } from "@/lib/toast";
import "./route-card-generation-alt.scss";
import "./extractions.scss";

function statusTone(status) {
  const s = String(status || "").toLowerCase();
  if (s === "analyzed" || s === "approved") return "success";
  if (s === "failed") return "danger";
  if (s === "analyzing" || s === "draft") return "warn";
  if (s === "open") return "info";
  return "neutral";
}

function docsFromDetail(detail) {
  const byRole = {};
  for (const d of detail?.documents || []) {
    byRole[d.role] = {
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

const STATUS_OPTIONS = [
  { label: "All statuses", value: null },
  { label: "Analyzed", value: "analyzed" },
  { label: "Draft", value: "draft" },
  { label: "Open", value: "open" },
  { label: "Failed", value: "failed" },
  { label: "Approved", value: "approved" },
];

const EMPTY_FILTERS = {
  empId: null,
  dept: null,
  status: null,
  fromDate: null,
  toDate: null,
};

export default function ExtractionsPage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState([]);
  const [users, setUsers] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [oarcOpen, setOarcOpen] = useState(false);
  const [oarcPayload, setOarcPayload] = useState(null);
  const [oarcDocs, setOarcDocs] = useState({});
  const [selected, setSelected] = useState([]);
  const [compareResult, setCompareResult] = useState(null);
  const navigate = useNavigate();

  const empOptions = useMemo(
    () => [
      { label: "All users", value: null },
      ...users.map((u) => ({
        label: `${u.empId} — ${u.name}${u.dept ? ` (${u.dept})` : ""}`,
        value: u.empId,
      })),
    ],
    [users],
  );

  const deptOptions = useMemo(() => {
    const fromMaster = departments.map((d) => ({
      label: d.label || d.name,
      value: d.value || d.name,
    }));
    const fromUsers = users
      .map((u) => (u.dept || "").trim())
      .filter(Boolean);
    const merged = new Map();
    for (const opt of fromMaster) merged.set(opt.value, opt);
    for (const name of fromUsers) {
      if (!merged.has(name)) merged.set(name, { label: name, value: name });
    }
    return [{ label: "All departments", value: null }, ...merged.values()];
  }, [departments, users]);

  const loadMeta = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const [uRes, dRows] = await Promise.all([
        fetchAdminUsers(),
        fetchDepartments().catch(() => []),
      ]);
      setUsers(uRes.users || []);
      setDepartments(Array.isArray(dRows) ? dRows : []);
    } catch (err) {
      setError(err.message || "Failed to load filter options");
    }
  }, [isAdmin]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (isAdmin) {
        const eRes = await fetchAdminExtractions({
          empId: applied.empId || undefined,
          dept: applied.dept || undefined,
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
    setFilters(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
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
    const token = getToken();
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
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
    setFilters((prev) => ({ ...prev, [key]: value }));

  return (
    <AppShell active="history">
        <div className="rc-hist">
          <PageHeader
            title={isAdmin ? "All extractions" : "My extractions"}
            subtitle={
              isAdmin
                ? "Browse every user’s analyzed sessions, open OARC preview, or print PDF."
                : "Your past analyses — open OARC preview or print PDF."
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

          <div className="flex gap-2 flex-wrap mb-3">
            {/* Analyze selected / jobs — hidden for now (queue from Jobs page instead)
            <Button
              type="button"
              label="Analyze selected"
              icon="pi pi-play"
              outlined
              size="small"
              disabled={(selected || []).length === 0}
              onClick={async () => {
                const ids = (selected || []).map((r) => r.sessionId).filter(Boolean);
                try {
                  await batchEnqueueAnalyze(ids);
                  toast.success(`Queued ${ids.length} session(s)`);
                  navigate("/jobs");
                } catch (e) {
                  toast.error(e.message || "Batch enqueue failed");
                }
              }}
            />
            */}
            <Button
              type="button"
              label="Compare selected (2)"
              icon="pi pi-arrows-h"
              outlined
              size="small"
              disabled={(selected || []).length !== 2}
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

          {isAdmin ? (
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
              <div className="rc-hist__filter">
                <label htmlFor="empFilter">User</label>
                <Dropdown
                  inputId="empFilter"
                  value={filters.empId}
                  options={empOptions}
                  onChange={(e) => patchFilter("empId", e.value)}
                  className="w-full"
                  placeholder="All users"
                  filter
                  showClear
                />
              </div>
              <div className="rc-hist__filter">
                <label htmlFor="deptFilter">Department</label>
                <Dropdown
                  inputId="deptFilter"
                  value={filters.dept}
                  options={deptOptions}
                  onChange={(e) => patchFilter("dept", e.value)}
                  className="w-full"
                  placeholder="All departments"
                  filter
                  showClear
                />
              </div>
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
                  onClick={applyFilters}
                />
                <Button
                  type="button"
                  label="Clear"
                  icon="pi pi-times"
                  size="small"
                  outlined
                  severity="secondary"
                  onClick={clearFilters}
                />
              </div>
            </div>
          ) : null}

          <TableComponent
            value={items}
            loading={loading || detailLoading}
            paginator
            rows={10}
            emptyMessage="No extractions yet."
            dataKey="sessionId"
            selectionMode="multiple"
            selection={selected}
            onSelectionChange={(e) => setSelected(e.value || [])}
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
                            secondary={[row.user.name, row.user.dept].filter(Boolean).join(" · ")}
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
                field: "status",
                body: (row) => (
                  <TableStatusBadge value={row.status || "—"} tone={statusTone(row.status)} />
                ),
              },
              {
                field: "operationCount",
                header: "Ops",
                sortable: true,
                style: { width: "5rem" },
              },
              {
                header: "Files",
                body: (row) => (
                  <TableFileChip
                    label={(row.documents || []).map((d) => d.role).join(", ") || ""}
                  />
                ),
              },
              {
                header: "Updated",
                sortable: true,
                field: "updatedAt",
                body: (row) =>
                  row.updatedAt ? new Date(row.updatedAt).toLocaleString() : "—",
              },
              {
                header: "Actions",
                style: { width: "9rem" },
                body: (row) => (
                  <TableActions>
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
                <dd>{detail.status}</dd>
              </div>
              {detail.user ? (
                <div>
                  <dt>User</dt>
                  <dd>
                    {detail.user.empId} — {detail.user.name}
                    {detail.user.dept ? ` (${detail.user.dept})` : ""}
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
      />
    </AppShell>
  );
}
