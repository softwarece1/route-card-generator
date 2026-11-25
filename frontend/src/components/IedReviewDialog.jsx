import { useCallback, useEffect, useState } from "react";
import { Button } from "primereact/button";
import { Column } from "primereact/column";
import { DataTable } from "primereact/datatable";
import { Dialog } from "primereact/dialog";
import { Message } from "primereact/message";
import { Tag } from "primereact/tag";
import SafeInputText from "@/components/SafeInputText";
import { getUser } from "@/lib/auth";
import { routeStatusLabel, routeStatusTone } from "@/lib/routeStatus";
import { toast } from "@/lib/toast";
import {
  completeIedReview,
  fetchMyExtractionDetail,
  updateRouteCard,
} from "@/services/routeCardApi";
import { TableStatusBadge } from "@/components/TableComponent";

/**
 * IED review surface: view shared route ops, edit setup / per-piece time (in hrs) only, complete review.
 * No extraction / generator UI.
 */
export default function IedReviewDialog({
  visible,
  sessionId,
  onHide,
  onCompleted,
}) {
  const user = getUser();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [ops, setOps] = useState([]);
  const [dirty, setDirty] = useState(false);

  const payload = detail?.payload || null;
  const routeId = payload?.id || detail?.routeCardId || null;
  const routeStatus = (payload?.status || detail?.routeStatus || "").toLowerCase();
  const canEdit = routeStatus === "ied_review";
  const partNo = detail?.partNumber || payload?.drawingInfo?.partNumber || "";
  const partName = detail?.partName || payload?.drawingInfo?.partName || "";

  const load = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError("");
    setDirty(false);
    try {
      const data = await fetchMyExtractionDetail(sessionId);
      setDetail(data);
      const rows = (data?.payload?.routeOperations || []).map((op) => ({ ...op }));
      setOps(rows);
    } catch (err) {
      setDetail(null);
      setOps([]);
      setError(err.message || "Could not load route for IED review");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (visible && sessionId) load();
  }, [visible, sessionId, load]);

  const patchOp = (id, patch) => {
    setOps((prev) =>
      prev.map((row) => (String(row.id) === String(id) ? { ...row, ...patch } : row)),
    );
    setDirty(true);
  };

  const saveOps = async () => {
    if (!routeId) return;
    setSaving(true);
    setError("");
    try {
      const next = await updateRouteCard(routeId, {
        operations: ops,
        comment: "IED standards update",
      });
      setOps((next.routeOperations || []).map((op) => ({ ...op })));
      setDetail((d) =>
        d
          ? {
              ...d,
              payload: next,
              routeStatus: next.status,
            }
          : d,
      );
      setDirty(false);
      toast.success("Standards saved.");
    } catch (err) {
      setError(err.message || "Save failed");
      toast.error(err.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const complete = async () => {
    if (!routeId) return;
    setSaving(true);
    setError("");
    try {
      if (dirty) {
        await updateRouteCard(routeId, {
          operations: ops,
          comment: "IED standards update",
        });
      }
      const next = await completeIedReview(routeId);
      toast.success("IED review completed — awaiting approval.");
      onCompleted?.(next);
      onHide?.();
    } catch (err) {
      setError(err.message || "Could not complete IED review");
      toast.error(err.message || "Could not complete IED review");
    } finally {
      setSaving(false);
    }
  };

  const tone = routeStatusTone(routeStatus);

  return (
    <Dialog
      header={`IED review${partNo ? ` — ${partNo}` : ""}${partName ? ` · ${partName}` : ""}`}
      visible={visible}
      style={{ width: "min(96vw, 56rem)" }}
      modal
      onHide={() => !saving && onHide?.()}
      footer={
        <div className="flex justify-content-end gap-2">
          <Button
            type="button"
            label="Close"
            outlined
            size="small"
            disabled={saving}
            onClick={() => onHide?.()}
          />
          {canEdit ? (
            <>
              <Button
                type="button"
                label="Save times"
                icon="pi pi-save"
                size="small"
                outlined
                loading={saving}
                disabled={saving || !dirty || !routeId}
                onClick={saveOps}
              />
              <Button
                type="button"
                label="Complete IED review"
                icon="pi pi-check"
                size="small"
                loading={saving}
                disabled={saving || !routeId}
                onClick={complete}
              />
            </>
          ) : null}
        </div>
      }
    >
      {error ? <Message severity="error" text={error} className="w-full mb-3" /> : null}
      <div className="flex align-items-center gap-2 mb-2 flex-wrap">
        <TableStatusBadge value={routeStatusLabel(routeStatus)} tone={tone} />
        {detail?.user ? (
          <span style={{ color: "var(--pmf-text-muted)", fontSize: "0.875rem" }}>
            From {detail.user.empId}
            {detail.user.name ? ` — ${detail.user.name}` : ""}
            {detail.user.sbu ? ` (${detail.user.sbu})` : ""}
          </span>
        ) : null}
        {!canEdit && routeStatus === "ied_complete" ? (
          <Tag value="Read-only — already sent for approval" severity="info" />
        ) : null}
      </div>
      <p style={{ marginTop: 0, color: "var(--pmf-text-muted)", fontSize: "0.875rem" }}>
        Edit setup and per-piece time (in hrs) only. Then complete IED review so engineering /
        dept head can approve.
      </p>
      <DataTable
        value={ops}
        loading={loading}
        size="small"
        paginator
        rows={10}
        rowsPerPageOptions={[10, 25, 50, 100]}
        paginatorTemplate="CurrentPageReport FirstPageLink PrevPageLink PageLinks NextPageLink LastPageLink RowsPerPageDropdown"
        currentPageReportTemplate="Showing {first}-{last} of {totalRecords} entries"
        emptyMessage={loading ? "Loading…" : "No operations on this route."}
        dataKey="id"
      >
        <Column field="opNo" header="Op" style={{ width: "4rem" }} />
        <Column field="operation" header="Operation" body={(row) => row.operation || "—"} />
        <Column
          header="Work centre"
          style={{ minWidth: "11rem" }}
          body={(row) => row.workCentre || "—"}
        />
        <Column
          header="Setup (in hrs)"
          style={{ width: "8rem" }}
          body={(row) =>
            canEdit ? (
              <SafeInputText
                profile="text"
                value={row.setup ?? ""}
                onChange={(e) => patchOp(row.id, { setup: e.target.value })}
                className="w-full"
                inputMode="decimal"
                placeholder="e.g. 0.25"
              />
            ) : (
              row.setup || "—"
            )
          }
        />
        <Column
          header="Per-piece (in hrs)"
          style={{ width: "9rem" }}
          body={(row) =>
            canEdit ? (
              <SafeInputText
                profile="text"
                value={row.time ?? ""}
                onChange={(e) => patchOp(row.id, { time: e.target.value })}
                className="w-full"
                inputMode="decimal"
                placeholder="e.g. 0.25"
              />
            ) : (
              row.time || "—"
            )
          }
        />
      </DataTable>
    </Dialog>
  );
}
