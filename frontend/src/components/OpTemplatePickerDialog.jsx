import { useEffect, useState } from "react";
import { Button } from "primereact/button";
import { Dialog } from "primereact/dialog";
import { Message } from "primereact/message";
import TableComponent, { TableStatusBadge } from "@/components/TableComponent";
import {
  getOperationTemplate,
  listOperationTemplates,
} from "@/services/routeCardApi";

const PLACEMENT_LABEL = {
  pre: "Before extracted ops",
  post: "After extracted ops",
  any: "Append at end",
};

/**
 * Pick a department operation pack and return full template (with steps).
 */
export default function OpTemplatePickerDialog({
  visible,
  onHide,
  onSelect,
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [items, setItems] = useState([]);
  const [applyingId, setApplyingId] = useState(null);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const res = await listOperationTemplates({ scope: "own" });
        if (!cancelled) setItems(res.items || []);
      } catch (err) {
        if (!cancelled) {
          setItems([]);
          setError(err.message || "Could not load templates");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [visible]);

  const apply = async (row) => {
    setApplyingId(row.id);
    setError("");
    try {
      const full = await getOperationTemplate(row.id);
      onSelect?.(full);
      onHide?.();
    } catch (err) {
      setError(err.message || "Could not load template");
    } finally {
      setApplyingId(null);
    }
  };

  return (
    <Dialog
      header="Add from operation template"
      visible={visible}
      onHide={onHide}
      style={{ width: "min(42rem, 96vw)" }}
      className="rc-otpl-dialog"
      modal
      dismissableMask
      footer={
        <div className="rc-otpl-dialog__footer">
          <Button type="button" label="Cancel" outlined size="small" onClick={onHide} />
        </div>
      }
    >
      {error ? <Message severity="error" text={error} className="w-full mb-3" /> : null}
      <p className="m-0 mb-3 text-sm" style={{ color: "#64748b" }}>
        Choose a pack from your department. All steps are inserted at once using the
        pack&apos;s placement hint (you can reorder afterward).
      </p>
      <TableComponent
        value={items}
        loading={loading}
        dataKey="id"
        paginator={false}
        emptyMessage="No templates in your department yet. Ask a department head to create some."
        columns={[
          { field: "name", header: "Template", sortable: true },
          {
            header: "Steps",
            style: { width: "5rem" },
            body: (row) => row.stepCount ?? 0,
          },
          {
            header: "Placement",
            style: { width: "12rem" },
            body: (row) => (
              <TableStatusBadge
                value={PLACEMENT_LABEL[row.placement] || row.placement || "any"}
                tone="info"
              />
            ),
          },
          {
            header: "",
            style: { width: "7rem" },
            body: (row) => (
              <Button
                type="button"
                label="Insert"
                size="small"
                loading={applyingId === row.id}
                disabled={Boolean(applyingId)}
                onClick={() => apply(row)}
              />
            ),
          },
        ]}
      />
    </Dialog>
  );
}
