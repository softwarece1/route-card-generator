import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Checkbox } from "primereact/checkbox";
import { Column } from "primereact/column";
import { confirmDialog } from "primereact/confirmdialog";
import { DataTable } from "primereact/datatable";
import { Dialog } from "primereact/dialog";
import { IconField } from "primereact/iconfield";
import { InputIcon } from "primereact/inputicon";
import { InputText } from "primereact/inputtext";
import { Message } from "primereact/message";
import { Tooltip } from "primereact/tooltip";
import { Navigate } from "react-router-dom";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import SafeInputText from "@/components/SafeInputText";
import TableComponent, { TableStatusBadge } from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { toast } from "@/lib/toast";
import {
  createDepartment,
  createSbu,
  fetchDepartments,
  fetchOrgSbus,
  softDeleteDepartment,
  updateDepartment,
  updateSbu,
} from "@/services/routeCardApi";
import "./org-structure.scss";

const emptySbu = () => ({
  code: "",
  name: "",
  plantId: "",
  isActive: true,
});

const emptyDept = () => ({
  code: "",
  name: "",
  isActive: true,
});

export default function OrgStructurePage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";
  const isSbuHead = user?.role === "sbu_head";
  const canManage = isAdmin || isSbuHead;

  const [sbus, setSbus] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [ownSbuId, setOwnSbuId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [search, setSearch] = useState("");
  const [expandedRows, setExpandedRows] = useState({});

  const [sbuDialogOpen, setSbuDialogOpen] = useState(false);
  const [sbuEditId, setSbuEditId] = useState(null);
  const [sbuForm, setSbuForm] = useState(emptySbu());

  const [deptDialogOpen, setDeptDialogOpen] = useState(false);
  const [deptEditId, setDeptEditId] = useState(null);
  const [deptForm, setDeptForm] = useState(emptyDept());
  const [deptSbuId, setDeptSbuId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (isSbuHead) {
        const ownName = (user?.sbu || "").trim();
        if (!ownName) {
          setDepartments([]);
          setOwnSbuId(null);
          setSbus([]);
          setError(
            "Your account has no SBU assigned — ask an admin to set it so you only see your SBU’s departments."
          );
          return;
        }
        const sbuRows = await fetchOrgSbus({ activeOnly: true });
        const ownSbu = (sbuRows || []).find(
          (s) => (s.name || "").trim() === ownName
        );
        // Backend forces actor.sbu scope; pass sbu for clarity / ownSbuId resolution
        const deptRows = await fetchDepartments({
          sbu: ownName,
          ...(ownSbu?.id ? { sbuId: ownSbu.id } : {}),
          activeOnly: false,
        });
        setDepartments(deptRows || []);
        setOwnSbuId(ownSbu?.id || deptRows?.[0]?.sbuId || null);
        setSbus([]);
        return;
      }

      // Admin: SBU list with nested departments
      const sbuRows = await fetchOrgSbus({ activeOnly: false });
      const deptRows = await fetchDepartments({ activeOnly: false });
      const bySbu = new Map();
      for (const d of deptRows || []) {
        const key = d.sbuId;
        if (key == null) continue;
        if (!bySbu.has(key)) bySbu.set(key, []);
        bySbu.get(key).push(d);
      }
      setSbus(
        (sbuRows || []).map((s) => ({
          ...s,
          departments: bySbu.get(s.id) || [],
        }))
      );
      setDepartments([]);
    } catch (err) {
      setSbus([]);
      setDepartments([]);
      setError(err.message || "Could not load org data");
    } finally {
      setLoading(false);
    }
  }, [isAdmin, isSbuHead, user?.sbu]);

  useEffect(() => {
    if (canManage) load();
  }, [canManage, load]);

  const filteredSbus = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return sbus;
    return sbus.filter((d) => {
      const blob = `${d.code || ""} ${d.name || ""} ${d.plantId || ""}`.toLowerCase();
      const deptHit = (d.departments || []).some((x) =>
        `${x.code || ""} ${x.name || ""}`.toLowerCase().includes(q)
      );
      return blob.includes(q) || deptHit;
    });
  }, [sbus, search]);

  const filteredDepts = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return departments;
    return departments.filter((d) => {
      const blob = `${d.code || ""} ${d.name || ""}`.toLowerCase();
      return blob.includes(q);
    });
  }, [departments, search]);

  const openCreateSbu = () => {
    setSbuEditId(null);
    setSbuForm(emptySbu());
    setDialogError("");
    setSbuDialogOpen(true);
  };

  const openEditSbu = (row) => {
    setSbuEditId(row.id);
    setSbuForm({
      code: row.code || "",
      name: row.name || "",
      plantId: row.plantId || "",
      isActive: row.isActive !== false,
    });
    setDialogError("");
    setSbuDialogOpen(true);
  };

  const saveSbu = async () => {
    const code = sbuForm.code.trim();
    const name = sbuForm.name.trim();
    const plantId = (sbuForm.plantId || "").trim();
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
      const body = { code, name, plantId, isActive: Boolean(sbuForm.isActive) };
      if (sbuEditId) await updateSbu(sbuEditId, body);
      else await createSbu(body);
      setSbuDialogOpen(false);
      toast.success(sbuEditId ? "SBU updated" : "SBU created");
      await load();
    } catch (err) {
      setDialogError(err.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const openCreateDept = (sbuRow) => {
    const sid = sbuRow?.id ?? ownSbuId;
    if (!sid) {
      toast.error(
        isSbuHead
          ? "Your account has no SBU assigned — ask an admin to set it."
          : "Select an SBU first"
      );
      return;
    }
    setDeptSbuId(sid);
    setDeptEditId(null);
    setDeptForm(emptyDept());
    setDialogError("");
    setDeptDialogOpen(true);
  };

  const openEditDept = (row) => {
    setDeptSbuId(row.sbuId || null);
    setDeptEditId(row.id);
    setDeptForm({
      code: row.code || "",
      name: row.name || "",
      isActive: row.isActive !== false,
    });
    setDialogError("");
    setDeptDialogOpen(true);
  };

  const saveDept = async () => {
    const code = deptForm.code.trim();
    const name = deptForm.name.trim();
    if (!code || !name) {
      setDialogError("Code and name are required");
      return;
    }
    if (!deptEditId && !deptSbuId) {
      setDialogError("Select an SBU first");
      return;
    }
    setSaving(true);
    setDialogError("");
    try {
      const body = {
        code,
        name,
        isActive: Boolean(deptForm.isActive),
        sbuId: deptSbuId,
      };
      if (deptEditId) await updateDepartment(deptEditId, body);
      else await createDepartment(body);
      setDeptDialogOpen(false);
      toast.success(deptEditId ? "Department updated" : "Department created");
      await load();
    } catch (err) {
      setDialogError(err.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const confirmSoftDeleteDept = (row) => {
    confirmDialog({
      message: `Deactivate department “${row.name || row.code}”? Users must be reassigned first. You can reactivate later.`,
      header: "Deactivate department",
      icon: "pi pi-exclamation-triangle",
      acceptClassName: "p-button-danger p-button-sm",
      rejectClassName: "p-button-outlined p-button-sm",
      acceptLabel: "Deactivate",
      rejectLabel: "Cancel",
      accept: async () => {
        try {
          await softDeleteDepartment(row.id);
          toast.success("Department deactivated");
          await load();
        } catch (err) {
          toast.error(err.message || "Could not deactivate");
        }
      },
    });
  };

  const toggleExpand = (row) => {
    if (!row?.id) return;
    setExpandedRows((prev) => {
      const next = { ...(prev || {}) };
      if (next[row.id]) delete next[row.id];
      else next[row.id] = true;
      return next;
    });
  };

  const nestedDepartmentsTemplate = (row) => (
    <div className="rc-org__nested" onClick={(e) => e.stopPropagation()}>
      <DataTable
        value={row.departments || []}
        dataKey="id"
        size="small"
        emptyMessage="No departments yet."
        className="rc-org__nested-table"
      >
        <Column field="code" header="Dept code" style={{ width: "12%" }} />
        <Column
          field="name"
          header="Dept name"
          style={{ width: "46%" }}
          bodyClassName="rc-org__dept-name-cell"
        />
        <Column
          header="Active"
          style={{ width: "12%" }}
          body={(d) => (
            <TableStatusBadge
              value={d.isActive ? "Yes" : "No"}
              tone={d.isActive ? "success" : "neutral"}
            />
          )}
        />
        <Column
          header="Actions"
          style={{ width: "30%" }}
          body={(d) => (
            <div className="rc-org__row-actions">
              <Button
                type="button"
                icon="pi pi-pencil"
                label="Edit"
                text
                size="small"
                onClick={() => openEditDept(d)}
              />
              {d.isActive ? (
                <Button
                  type="button"
                  icon="pi pi-trash"
                  label="Deactivate"
                  text
                  size="small"
                  severity="danger"
                  onClick={() => confirmSoftDeleteDept(d)}
                />
              ) : null}
            </div>
          )}
        />
      </DataTable>
    </div>
  );

  if (!canManage) {
    return <Navigate to="/generator" replace />;
  }

  const deptColumns = [
    { field: "code", header: "Dept code", sortable: true, style: { width: "8rem" } },
    { field: "name", header: "Dept name", sortable: true },
    {
      header: "Active",
      style: { width: "6rem" },
      body: (d) => (
        <TableStatusBadge
          value={d.isActive ? "Yes" : "No"}
          tone={d.isActive ? "success" : "neutral"}
        />
      ),
    },
    {
      header: "Actions",
      style: { width: "14rem", whiteSpace: "nowrap" },
      body: (d) => (
        <div className="rc-org__row-actions">
          <Button
            type="button"
            icon="pi pi-pencil"
            label="Edit"
            text
            size="small"
            onClick={() => openEditDept(d)}
          />
          {d.isActive ? (
            <Button
              type="button"
              icon="pi pi-trash"
              label="Deactivate"
              text
              size="small"
              severity="danger"
              onClick={() => confirmSoftDeleteDept(d)}
            />
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <AppShell active="org">
      <div className="rc-org">
        <PageHeader
          title={isSbuHead ? "Departments" : "Org structure"}
          subtitle={
            isSbuHead
              ? `Departments in ${user?.sbu || "your SBU"}.`
              : "Expand an SBU to see its departments."
          }
          icon="pi pi-sitemap"
          actions={
            <div className="rc-org__header-actions">
              <IconField iconPosition="left" className="rc-org__search">
                <InputIcon className="pi pi-search" />
                <InputText
                  placeholder={isSbuHead ? "Search department…" : "Search SBU…"}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </IconField>
              {isAdmin ? (
                <Button
                  type="button"
                  label="Add SBU"
                  icon="pi pi-plus"
                  size="small"
                  onClick={openCreateSbu}
                />
              ) : null}
              {isSbuHead ? (
                <Button
                  type="button"
                  label="Add dept"
                  icon="pi pi-plus"
                  size="small"
                  onClick={() => openCreateDept(null)}
                />
              ) : null}
              <Button
                type="button"
                label="Refresh"
                icon="pi pi-refresh"
                size="small"
                outlined
                onClick={() => load()}
              />
            </div>
          }
        />
        {error ? <Message severity="error" text={error} className="w-full mb-3" /> : null}

        <div className="rc-org__shell">
          <div className="rc-org__panel">
            {isSbuHead ? (
              <TableComponent
                value={filteredDepts}
                loading={loading}
                dataKey="id"
                paginator
                rows={10}
                emptyMessage={
                  search.trim()
                    ? "No departments match your search."
                    : !user?.sbu
                      ? "Your account has no SBU assigned."
                      : "No departments yet."
                }
                columns={deptColumns}
              />
            ) : (
              <>
                <Tooltip
                  target=".rc-org .p-row-toggler"
                  content="view departments"
                  position="top"
                />
                <TableComponent
                  value={filteredSbus}
                  loading={loading}
                  dataKey="id"
                  paginator
                  rows={10}
                  sortField="plantId"
                  sortOrder={1}
                  className="rc-org__sbu-table"
                  emptyMessage={
                    search.trim() ? "No SBUs match your search." : "No SBUs yet."
                  }
                  expandedRows={expandedRows}
                  onRowToggle={(e) => setExpandedRows(e.data)}
                  onRowClick={(e) => toggleExpand(e.data)}
                  rowExpansionTemplate={nestedDepartmentsTemplate}
                  columns={[
                    { type: "expander", style: { width: "2.75rem" } },
                    {
                      field: "code",
                      header: "Code",
                      sortable: true,
                      style: { width: "7.5rem" },
                    },
                    {
                      field: "name",
                      header: "Name",
                      sortable: true,
                      style: { width: "14rem", maxWidth: "14rem" },
                      className: "rc-org__name-cell",
                    },
                    {
                      field: "plantId",
                      header: "Plant ID",
                      sortable: true,
                      style: { width: "7rem" },
                      body: (row) => row.plantId || "—",
                      sortFunction: (event) => {
                        const { data, order } = event;
                        const dir = order === -1 ? -1 : 1;
                        return [...(data || [])].sort((a, b) => {
                          const pa = (a.plantId || "").trim();
                          const pb = (b.plantId || "").trim();
                          if (!pa && !pb) {
                            return dir * (a.name || "").localeCompare(b.name || "");
                          }
                          if (!pa) return 1;
                          if (!pb) return -1;
                          const c = pa.localeCompare(pb, undefined, {
                            numeric: true,
                          });
                          return (
                            dir * (c || (a.name || "").localeCompare(b.name || ""))
                          );
                        });
                      },
                    },
                    {
                      header: "Depts",
                      style: { width: "4.5rem" },
                      body: (row) => (
                        <span className="rc-org__count-chip">
                          {(row.departments || []).length}
                        </span>
                      ),
                    },
                    {
                      header: "Active",
                      style: { width: "5.5rem" },
                      body: (row) => (
                        <TableStatusBadge
                          value={row.isActive ? "Yes" : "No"}
                          tone={row.isActive ? "success" : "neutral"}
                        />
                      ),
                    },
                    {
                      header: "Actions",
                      style: { width: "13.5rem", whiteSpace: "nowrap" },
                      body: (row) => (
                        <div
                          className="rc-org__row-actions"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Button
                            type="button"
                            icon="pi pi-plus"
                            label="Add dept"
                            size="small"
                            text
                            className="rc-org__add-dept-btn"
                            onClick={() => openCreateDept(row)}
                          />
                          <Button
                            type="button"
                            icon="pi pi-pencil"
                            label="Edit"
                            size="small"
                            text
                            onClick={() => openEditSbu(row)}
                          />
                        </div>
                      ),
                    },
                  ]}
                />
              </>
            )}
          </div>
        </div>

        <Dialog
          header={sbuEditId ? "Edit SBU" : "Add SBU"}
          visible={sbuDialogOpen}
          style={{ width: "min(26rem, 94vw)" }}
          modal
          onHide={() => !saving && setSbuDialogOpen(false)}
          footer={
            <div className="flex gap-2 justify-content-end">
              <Button
                type="button"
                label="Cancel"
                size="small"
                outlined
                disabled={saving}
                onClick={() => setSbuDialogOpen(false)}
              />
              <Button type="button" label="Save" size="small" loading={saving} onClick={saveSbu} />
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
                value={sbuForm.code}
                onChange={(e) =>
                  setSbuForm((f) => ({
                    ...f,
                    code: e.target.value.toUpperCase().replace(/\s+/g, "_"),
                  }))
                }
                disabled={saving || Boolean(sbuEditId)}
                className="w-full"
                placeholder="e.g. MR"
              />
            </label>
            <label>
              Name
              <SafeInputText
                profile="label"
                value={sbuForm.name}
                onChange={(e) => setSbuForm((f) => ({ ...f, name: e.target.value }))}
                disabled={saving}
                className="w-full"
              />
            </label>
            <label>
              Plant ID
              <SafeInputText
                profile="text"
                value={sbuForm.plantId}
                onChange={(e) =>
                  setSbuForm((f) => ({ ...f, plantId: e.target.value.trim() }))
                }
                disabled={saving}
                className="w-full"
                placeholder="e.g. 1110"
              />
            </label>
            <label className="flex align-items-center gap-2">
              <Checkbox
                inputId="sbuActive"
                checked={Boolean(sbuForm.isActive)}
                onChange={(e) =>
                  setSbuForm((f) => ({ ...f, isActive: Boolean(e.checked) }))
                }
                disabled={saving}
              />
              <span>Active</span>
            </label>
          </div>
        </Dialog>

        <Dialog
          header={deptEditId ? "Edit department" : "Add department"}
          visible={deptDialogOpen}
          style={{ width: "min(26rem, 94vw)" }}
          modal
          onHide={() => !saving && setDeptDialogOpen(false)}
          footer={
            <div className="flex gap-2 justify-content-end">
              <Button
                type="button"
                label="Cancel"
                size="small"
                outlined
                disabled={saving}
                onClick={() => setDeptDialogOpen(false)}
              />
              <Button type="button" label="Save" size="small" loading={saving} onClick={saveDept} />
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
                value={deptForm.code}
                onChange={(e) =>
                  setDeptForm((f) => ({
                    ...f,
                    code: e.target.value.toUpperCase().replace(/\s+/g, "_"),
                  }))
                }
                disabled={saving || Boolean(deptEditId)}
                className="w-full"
                placeholder="e.g. PMG"
              />
            </label>
            <label>
              Name
              <SafeInputText
                profile="label"
                value={deptForm.name}
                onChange={(e) => setDeptForm((f) => ({ ...f, name: e.target.value }))}
                disabled={saving}
                className="w-full"
              />
            </label>
            <label className="flex align-items-center gap-2">
              <Checkbox
                inputId="deptActive"
                checked={Boolean(deptForm.isActive)}
                onChange={(e) =>
                  setDeptForm((f) => ({ ...f, isActive: Boolean(e.checked) }))
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
