import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Checkbox } from "primereact/checkbox";
import { Dialog } from "primereact/dialog";
import { IconField } from "primereact/iconfield";
import { InputIcon } from "primereact/inputicon";
import { InputText } from "primereact/inputtext";
import { Message } from "primereact/message";
import { Navigate } from "react-router-dom";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import SafeInputText from "@/components/SafeInputText";
import TableComponent, { TableActions, TableStatusBadge } from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { toast } from "@/lib/toast";
import {
  createSbu,
  fetchOrgSbus,
  updateSbu,
} from "@/services/routeCardApi";
import "./org-structure.scss";

const emptySbu = () => ({
  code: "",
  name: "",
  plantId: "",
  sortOrder: 0,
  isActive: true,
});

export default function OrgStructurePage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";

  const [sbus, setSbus] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [search, setSearch] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editId, setEditId] = useState(null);
  const [form, setForm] = useState(emptySbu());

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await fetchOrgSbus({ activeOnly: false });
      setSbus(rows || []);
    } catch (err) {
      setSbus([]);
      setError(err.message || "Could not load SBUs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) load();
  }, [isAdmin, load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return sbus;
    return sbus.filter((d) => {
      const blob = `${d.code || ""} ${d.name || ""} ${d.plantId || ""}`.toLowerCase();
      return blob.includes(q);
    });
  }, [sbus, search]);

  const openCreate = () => {
    setEditId(null);
    setForm(emptySbu());
    setDialogError("");
    setDialogOpen(true);
  };

  const openEdit = (row) => {
    setEditId(row.id);
    setForm({
      code: row.code || "",
      name: row.name || "",
      plantId: row.plantId || "",
      sortOrder: row.sortOrder ?? 0,
      isActive: row.isActive !== false,
    });
    setDialogError("");
    setDialogOpen(true);
  };

  const save = async () => {
    const code = form.code.trim();
    const name = form.name.trim();
    const plantId = (form.plantId || "").trim();
    if (!code || !name) {
      setDialogError("Code and name are required");
      return;
    }
    if (!plantId) {
      setDialogError("Plant ID is required");
      return;
    }
    setSaving(true);
    setDialogError("");
    try {
      const body = {
        code,
        name,
        plantId,
        sortOrder: Number(form.sortOrder) || 0,
        isActive: Boolean(form.isActive),
      };
      if (editId) await updateSbu(editId, body);
      else await createSbu(body);
      setDialogOpen(false);
      toast.success(editId ? "SBU updated" : "SBU created");
      await load();
    } catch (err) {
      setDialogError(err.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!isAdmin) {
    return <Navigate to="/generator" replace />;
  }

  return (
    <AppShell active="org">
      <div className="rc-org">
        <PageHeader
          title="SBUs"
          subtitle="One plant code (WERKS) per SBU — used for work centres and SAP sync."
          icon="pi pi-sitemap"
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

        <div className="rc-org__shell">
          <div className="rc-org__tabs-row">
            <div className="rc-org__pane-title">SBUs</div>
            <div className="rc-org__tabs-tools">
              <IconField iconPosition="left" className="rc-org__search">
                <InputIcon className="pi pi-search" />
                <InputText
                  placeholder="Search SBU…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </IconField>
              <Button
                type="button"
                label="Add SBU"
                icon="pi pi-plus"
                size="small"
                onClick={openCreate}
              />
            </div>
          </div>

          <div className="rc-org__panel">
            <TableComponent
              value={filtered}
              loading={loading}
              dataKey="id"
              paginator
              rows={15}
              emptyMessage={search.trim() ? "No SBUs match your search." : "No SBUs yet."}
              columns={[
                { type: "index", header: "#", style: { width: "3rem" } },
                { field: "code", header: "Code", sortable: true, style: { width: "8rem" } },
                { field: "name", header: "Name", sortable: true },
                {
                  field: "plantId",
                  header: "Plant ID",
                  sortable: true,
                  style: { width: "8rem" },
                  body: (row) => row.plantId || "—",
                },
                {
                  header: "Active",
                  style: { width: "6rem" },
                  body: (row) => (
                    <TableStatusBadge
                      value={row.isActive ? "Yes" : "No"}
                      tone={row.isActive ? "success" : "neutral"}
                    />
                  ),
                },
                {
                  header: "Actions",
                  style: { width: "5rem" },
                  body: (row) => (
                    <TableActions>
                      <Button
                        type="button"
                        icon="pi pi-pencil"
                        rounded
                        text
                        size="small"
                        aria-label="Edit"
                        onClick={() => openEdit(row)}
                      />
                    </TableActions>
                  ),
                },
              ]}
            />
          </div>
        </div>

        <Dialog
          header={editId ? "Edit SBU" : "Add SBU"}
          visible={dialogOpen}
          style={{ width: "min(26rem, 94vw)" }}
          modal
          onHide={() => !saving && setDialogOpen(false)}
          footer={
            <div className="flex gap-2 justify-content-end">
              <Button
                type="button"
                label="Cancel"
                size="small"
                outlined
                disabled={saving}
                onClick={() => setDialogOpen(false)}
              />
              <Button
                type="button"
                label="Save"
                size="small"
                loading={saving}
                onClick={save}
              />
            </div>
          }
        >
          {dialogError ? (
            <Message severity="error" text={dialogError} className="w-full mb-2" />
          ) : null}
          <div className="flex flex-column gap-2" style={{ fontSize: "0.85rem" }}>
            <label>
              Code
              <SafeInputText
                profile="text"
                value={form.code}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    code: e.target.value.toUpperCase().replace(/\s+/g, "_"),
                  }))
                }
                disabled={saving || Boolean(editId)}
                className="w-full"
                placeholder="e.g. MR"
              />
            </label>
            <label>
              Name
              <SafeInputText
                profile="label"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                disabled={saving}
                className="w-full"
              />
            </label>
            <label>
              Plant ID
              <SafeInputText
                profile="text"
                value={form.plantId}
                onChange={(e) =>
                  setForm((f) => ({ ...f, plantId: e.target.value.trim() }))
                }
                disabled={saving}
                className="w-full"
                placeholder="e.g. 1110"
              />
            </label>
            <label>
              Sort order
              <SafeInputText
                profile="text"
                value={String(form.sortOrder ?? 0)}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    sortOrder: e.target.value.replace(/\D/g, "").slice(0, 6) || "0",
                  }))
                }
                disabled={saving}
                className="w-full"
              />
            </label>
            <label className="flex align-items-center gap-2">
              <Checkbox
                inputId="sbuActive"
                checked={Boolean(form.isActive)}
                onChange={(e) =>
                  setForm((f) => ({ ...f, isActive: Boolean(e.checked) }))
                }
                disabled={saving}
              />
              <span>Active</span>
            </label>
          </div>
        </Dialog>
      </div>
    </AppShell>
  );
}
