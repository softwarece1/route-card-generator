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
import {
  fetchAdminExtractions,
  fetchAdminExtractionDetail,
  fetchAdminUsers,
  fetchMyExtractionDetail,
  fetchMyExtractions,
  sessionDocumentFileUrl,
} from "@/services/routeCardApi";
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
