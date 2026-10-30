import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Column } from "primereact/column";
import { DataTable } from "primereact/datatable";
import { Dialog } from "primereact/dialog";
import { Dropdown } from "primereact/dropdown";
import { Message } from "primereact/message";
import { Tag } from "primereact/tag";
import SafeInputText from "@/components/SafeInputText";
import { getUser } from "@/lib/auth";
import { routeStatusLabel, routeStatusTone } from "@/lib/routeStatus";
import { toast } from "@/lib/toast";
import {
  completeIedReview,
  fetchMyExtractionDetail,
  fetchWorkCenterCatalog,
  updateRouteCard,
} from "@/services/routeCardApi";
import { TableStatusBadge } from "@/components/TableComponent";

/**
 * IED review surface: view shared route ops, edit setup / per-piece time / WC, complete review.
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
  const [wcCatalog, setWcCatalog] = useState([]);
  const [dirty, setDirty] = useState(false);

  const payload = detail?.payload || null;
  const routeId = payload?.id || detail?.routeCardId || null;
  const routeStatus = (payload?.status || detail?.routeStatus || "").toLowerCase();
  const canEdit = routeStatus === "ied_review";
  const partNo = detail?.partNumber || payload?.drawingInfo?.partNumber || "";
  const partName = detail?.partName || payload?.drawingInfo?.partName || "";

  const wcOptions = useMemo(
    () =>
      (wcCatalog || []).map((w) => ({
        label: w.code ? `${w.code} — ${w.name || ""}` : w.name || String(w.id),
        value: w.id,
        code: w.code,
        name: w.name,
      })),
    [wcCatalog],
  );

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
      const dept = data?.user?.dept || user?.dept || "";
      try {
        const catalog = await fetchWorkCenterCatalog(dept || undefined);
        setWcCatalog(Array.isArray(catalog) ? catalog : catalog?.items || []);
      } catch {
        setWcCatalog([]);
      }
    } catch (err) {
      setDetail(null);
      setOps([]);
      setError(err.message || "Could not load route for IED review");
    } finally {
      setLoading(false);
    }
  }, [sessionId, user?.dept]);

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
      toast.success("IED review complete — sent for approval.");
      onCompleted?.(next);
      onHide?.();
    } catch (err) {
      setError(err.message || "Complete failed");
      toast.error(err.message || "Complete failed");
    } finally {
      setSaving(false);
    }
  };

  const tone = routeStatusTone(routeStatus);

  return (
    <Dialog
      header={
        partNo
          ? `IED review — ${partNo}${partName ? ` · ${partName}` : ""}`
          : "IED review"
      }
      visible={visible}
      onHide={() => !saving && onHide?.()}
      style={{ width: "min(96vw, 64rem)" }}
      maximizable
      modal
      className="ied-review-dialog"
      footer={
        <div className="flex justify-content-end gap-2 flex-wrap">
          <Button
            type="button"
            label="Close"
            outlined
            size="small"
            disabled={saving}
            onClick={() => onHide?.()}
          />
          {canEdit && (
            <>
              <Button
                type="button"
                label="Save standards"
                icon="pi pi-save"
                outlined
                size="small"
                loading={saving}
                disabled={!routeId || !dirty}
                onClick={saveOps}
              />
              <Button
                type="button"
                label="Complete IED review"
                icon="pi pi-check-circle"
                size="small"
                loading={saving}
                disabled={!routeId}
                onClick={complete}
              />
            </>
          )}
        </div>
      }
    >
      {error ? <Message severity="error" text={error} className="w-full mb-2" /> : null}
      <div className="flex align-items-center gap-2 mb-3 flex-wrap">
        <TableStatusBadge value={routeStatusLabel(routeStatus)} tone={tone} />
        {detail?.user ? (
          <span style={{ color: "var(--pmf-text-muted)", fontSize: "0.875rem" }}>
            From {detail.user.empId}
            {detail.user.name ? ` — ${detail.user.name}` : ""}
            {detail.user.dept ? ` (${detail.user.dept})` : ""}
          </span>
        ) : null}
        {!canEdit && routeStatus === "ied_complete" ? (
          <Tag value="Read-only — already sent for approval" severity="info" />
        ) : null}
      </div>
      <p style={{ marginTop: 0, color: "var(--pmf-text-muted)", fontSize: "0.875rem" }}>
        Set standard setup time, per-piece time, and work centre. Then complete IED review so
        engineering / dept head can approve.
      </p>
      <DataTable
        value={ops}
        loading={loading}
        size="small"
        paginator
        rows={12}
        emptyMessage={loading ? "Loading…" : "No operations on this route."}
        dataKey="id"
      >
        <Column field="opNo" header="Op" style={{ width: "4rem" }} />
        <Column
          field="operation"
          header="Operation"
          body={(row) =>
            canEdit ? (
              <SafeInputText
                profile="text"
                value={row.operation ?? ""}
                onChange={(e) => patchOp(row.id, { operation: e.target.value })}
                className="w-full"
              />
            ) : (
              row.operation || "—"
            )
          }
        />
        <Column
          header="Work centre"
          style={{ minWidth: "11rem" }}
          body={(row) =>
            canEdit && wcOptions.length > 0 ? (
              <Dropdown
                value={row.workCentreId ?? null}
                options={wcOptions}
                placeholder="Select WC"
                showClear
                filter
                className="w-full"
                onChange={(e) => {
                  const wc = (wcCatalog || []).find((w) => w.id === e.value);
                  patchOp(row.id, {
                    workCentreId: e.value ?? null,
                    workCentre: wc ? wc.code || wc.name : "",
                    linkStatus: "manual_override",
                  });
                }}
              />
            ) : canEdit ? (
              <SafeInputText
                profile="text"
                value={row.workCentre ?? ""}
                onChange={(e) =>
                  patchOp(row.id, {
                    workCentre: e.target.value,
                    workCentreId: null,
                    linkStatus: "manual_override",
                  })
                }
                className="w-full"
              />
            ) : (
              row.workCentre || "—"
            )
          }
        />
        <Column
          header="Setup"
          style={{ width: "7rem" }}
          body={(row) =>
            canEdit ? (
              <SafeInputText
                profile="text"
                value={row.setup ?? ""}
                onChange={(e) => patchOp(row.id, { setup: e.target.value })}
                className="w-full"
              />
            ) : (
              row.setup || "—"
            )
          }
        />
        <Column
          header="Per-piece"
          style={{ width: "7rem" }}
          body={(row) =>
            canEdit ? (
              <SafeInputText
                profile="text"
                value={row.time ?? ""}
                onChange={(e) => patchOp(row.id, { time: e.target.value })}
                className="w-full"
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
