import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Checkbox } from "primereact/checkbox";
import { Dialog } from "primereact/dialog";
import { Dropdown } from "primereact/dropdown";
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
  createDepartment,
  createPlant,
  fetchOrgDepartments,
  fetchPlants,
  updateDepartment,
  updatePlant,
} from "@/services/routeCardApi";
import "./org-structure.scss";

const emptyPlant = () => ({
  code: "",
  name: "",
  description: "",
  sortOrder: 0,
  isActive: true,
});

const emptyDept = () => ({
  code: "",
  name: "",
  plantId: "",
  sortOrder: 0,
  isActive: true,
});

export default function OrgStructurePage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";

  const [tab, setTab] = useState(0);
  const [plants, setPlants] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState("");

  const [plantOpen, setPlantOpen] = useState(false);
  const [plantEditId, setPlantEditId] = useState(null);
  const [plantForm, setPlantForm] = useState(emptyPlant());

  const [deptOpen, setDeptOpen] = useState(false);
  const [deptEditId, setDeptEditId] = useState(null);
  const [deptForm, setDeptForm] = useState(emptyDept());
  const [plantSearch, setPlantSearch] = useState("");
  const [deptSearch, setDeptSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [p, d] = await Promise.all([
        fetchPlants({ activeOnly: false }),
        fetchOrgDepartments({ activeOnly: false }),
      ]);
      setPlants(p || []);
      setDepartments(d || []);
    } catch (err) {
      setPlants([]);
      setDepartments([]);
      setError(err.message || "Could not load org structure");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) load();
  }, [isAdmin, load]);

  const plantOptions = useMemo(
    () =>
      (plants || [])
        .filter((p) => p.isActive)
        .map((p) => ({
          label: `${p.code} — ${p.name}`,
          value: p.code,
        })),
    [plants],
  );

  const plantNameByCode = useMemo(() => {
    const m = new Map();
    for (const p of plants) m.set(p.code, p.name);
    return m;
  }, [plants]);

  const filteredPlants = useMemo(() => {
    const q = plantSearch.trim().toLowerCase();
    if (!q) return plants;
    return plants.filter((p) => {
      const blob = `${p.code || ""} ${p.name || ""} ${p.description || ""}`.toLowerCase();
      return blob.includes(q);
    });
  }, [plants, plantSearch]);

  const filteredDepartments = useMemo(() => {
    const q = deptSearch.trim().toLowerCase();
    if (!q) return departments;
    return departments.filter((d) => {
      const plantName = plantNameByCode.get(d.plantId) || "";
      const blob = `${d.code || ""} ${d.name || ""} ${d.plantId || ""} ${plantName}`.toLowerCase();
      return blob.includes(q);
    });
  }, [departments, deptSearch, plantNameByCode]);

  const openCreatePlant = () => {
    setPlantEditId(null);
    setPlantForm(emptyPlant());
    setDialogError("");
    setPlantOpen(true);
  };

  const openEditPlant = (row) => {
    setPlantEditId(row.id);
    setPlantForm({
      code: row.code || "",
      name: row.name || "",
      description: row.description || "",
      sortOrder: row.sortOrder ?? 0,
      isActive: row.isActive !== false,
    });
    setDialogError("");
    setPlantOpen(true);
  };

  const savePlant = async () => {
    const code = plantForm.code.trim();
    const name = plantForm.name.trim();
    if (!code || !name) {
      setDialogError("Code and name are required");
      return;
    }
    setSaving(true);
    setDialogError("");
    try {
      const body = {
        code,
        name,
        description: plantForm.description.trim(),
        sortOrder: Number(plantForm.sortOrder) || 0,
        isActive: Boolean(plantForm.isActive),
      };
      if (plantEditId) await updatePlant(plantEditId, body);
      else await createPlant(body);
      setPlantOpen(false);
      toast.success(plantEditId ? "Plant updated" : "Plant created");
      await load();
    } catch (err) {
      setDialogError(err.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const openCreateDept = () => {
    setDeptEditId(null);
    setDeptForm({
      ...emptyDept(),
      plantId: plantOptions[0]?.value || "",
    });
    setDialogError("");
    setDeptOpen(true);
  };

  const openEditDept = (row) => {
    setDeptEditId(row.id);
    setDeptForm({
      code: row.code || "",
      name: row.name || "",
      plantId: row.plantId || "",
      sortOrder: row.sortOrder ?? 0,
      isActive: row.isActive !== false,
    });
    setDialogError("");
    setDeptOpen(true);
  };

  const saveDept = async () => {
    const code = deptForm.code.trim();
    const name = deptForm.name.trim();
    if (!code || !name) {
      setDialogError("Code and name are required");
      return;
    }
    if (!deptForm.plantId) {
      setDialogError("Select a plant");
      return;
    }
    setSaving(true);
    setDialogError("");
    try {
      const body = {
        code,
        name,
        plantId: deptForm.plantId,
        sortOrder: Number(deptForm.sortOrder) || 0,
        isActive: Boolean(deptForm.isActive),
      };
      if (deptEditId) await updateDepartment(deptEditId, body);
      else await createDepartment(body);
      setDeptOpen(false);
      toast.success(deptEditId ? "Department updated" : "Department created");
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
          title="Plants & departments"
          subtitle="Admin master data — plants (WERKS) and departments under each plant."
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
            <div className="rc-org__tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={tab === 0}
                className={`rc-org__tab${tab === 0 ? " is-active" : ""}`}
                onClick={() => setTab(0)}
              >
                Plants
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 1}
                className={`rc-org__tab${tab === 1 ? " is-active" : ""}`}
                onClick={() => setTab(1)}
              >
                Departments
              </button>
            </div>
            <div className="rc-org__tabs-tools">
              {tab === 0 ? (
                <>
                  <IconField iconPosition="left" className="rc-org__search">
                    <InputIcon className="pi pi-search" />
                    <InputText
                      placeholder="Search plant"
                      value={plantSearch}
                      onChange={(e) => setPlantSearch(e.target.value)}
                    />
                  </IconField>
                  <Button
                    type="button"
                    label="Add plant"
                    icon="pi pi-plus"
                    size="small"
                    onClick={openCreatePlant}
                  />
                </>
              ) : (
                <>
                  <IconField iconPosition="left" className="rc-org__search">
                    <InputIcon className="pi pi-search" />
                    <InputText
                      placeholder="Search department"
                      value={deptSearch}
                      onChange={(e) => setDeptSearch(e.target.value)}
                    />
                  </IconField>
                  <Button
                    type="button"
                    label="Add department"
                    icon="pi pi-plus"
                    size="small"
                    onClick={openCreateDept}
                    disabled={plantOptions.length === 0}
                  />
                </>
              )}
            </div>
          </div>

          <div className="rc-org__panel">
            {tab === 0 ? (
              <TableComponent
                value={filteredPlants}
                loading={loading}
                dataKey="id"
                paginator
                rows={15}
                emptyMessage={plantSearch.trim() ? "No plants match your search." : "No plants yet."}
                columns={[
                  { type: "index", header: "#", style: { width: "3rem" } },
                  { field: "code", header: "Code", sortable: true, style: { width: "7rem" } },
                  { field: "name", header: "Name", sortable: true },
                  {
                    field: "description",
                    header: "Description",
                    body: (row) => row.description || "—",
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
                          onClick={() => openEditPlant(row)}
                        />
                      </TableActions>
                    ),
                  },
                ]}
              />
            ) : (
              <>
                {plantOptions.length === 0 ? (
                  <Message
                    severity="warn"
                    className="w-full mb-2"
                    text="Create at least one active plant before adding departments."
                  />
                ) : null}
                <TableComponent
                  value={filteredDepartments}
                  loading={loading}
                  dataKey="id"
                  paginator
                  rows={15}
                  emptyMessage={
                    deptSearch.trim()
                      ? "No departments match your search."
                      : "No departments yet."
                  }
                  columns={[
                    { type: "index", header: "#", style: { width: "3rem" } },
                    { field: "code", header: "Code", sortable: true, style: { width: "8rem" } },
                    { field: "name", header: "Name", sortable: true },
                    {
                      header: "Plant",
                      sortable: true,
                      field: "plantId",
                      style: { width: "12rem" },
                      body: (row) => {
                        const label = plantNameByCode.get(row.plantId);
                        return label ? `${row.plantId} — ${label}` : row.plantId || "—";
                      },
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
                            onClick={() => openEditDept(row)}
                          />
                        </TableActions>
                      ),
                    },
                  ]}
                />
              </>
            )}
          </div>
        </div>

        <Dialog
          header={plantEditId ? "Edit plant" : "Add plant"}
          visible={plantOpen}
          style={{ width: "min(26rem, 94vw)" }}
          modal
          onHide={() => !saving && setPlantOpen(false)}
          footer={
            <div className="flex gap-2 justify-content-end">
              <Button
                type="button"
                label="Cancel"
                size="small"
                outlined
                disabled={saving}
                onClick={() => setPlantOpen(false)}
              />
              <Button
                type="button"
                label="Save"
                size="small"
                loading={saving}
                onClick={savePlant}
              />
            </div>
          }
        >
          {dialogError ? (
            <Message severity="error" text={dialogError} className="w-full mb-2" />
          ) : null}
          <div className="flex flex-column gap-2" style={{ fontSize: "0.85rem" }}>
            <label>
              Code (WERKS)
              <SafeInputText
                profile="text"
                value={plantForm.code}
                onChange={(e) =>
                  setPlantForm((f) => ({ ...f, code: e.target.value.trim() }))
                }
                disabled={saving || Boolean(plantEditId)}
                className="w-full"
                placeholder="e.g. 1100"
              />
            </label>
            <label>
              Name
              <SafeInputText
                profile="label"
                value={plantForm.name}
                onChange={(e) => setPlantForm((f) => ({ ...f, name: e.target.value }))}
                disabled={saving}
                className="w-full"
              />
            </label>
            <label>
              Description
              <SafeInputText
                profile="text"
                value={plantForm.description}
                onChange={(e) =>
                  setPlantForm((f) => ({ ...f, description: e.target.value }))
                }
                disabled={saving}
                className="w-full"
              />
            </label>
            <label>
              Sort order
              <SafeInputText
                profile="text"
                value={String(plantForm.sortOrder ?? 0)}
                onChange={(e) =>
                  setPlantForm((f) => ({
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
                inputId="plantActive"
                checked={Boolean(plantForm.isActive)}
                onChange={(e) =>
                  setPlantForm((f) => ({ ...f, isActive: Boolean(e.checked) }))
                }
                disabled={saving}
              />
              <span>Active</span>
            </label>
          </div>
        </Dialog>

        <Dialog
          header={deptEditId ? "Edit department" : "Add department"}
          visible={deptOpen}
          style={{ width: "min(26rem, 94vw)" }}
          modal
          onHide={() => !saving && setDeptOpen(false)}
          footer={
            <div className="flex gap-2 justify-content-end">
              <Button
                type="button"
                label="Cancel"
                size="small"
                outlined
                disabled={saving}
                onClick={() => setDeptOpen(false)}
              />
              <Button
                type="button"
                label="Save"
                size="small"
                loading={saving}
                onClick={saveDept}
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
                value={deptForm.code}
                onChange={(e) =>
                  setDeptForm((f) => ({
                    ...f,
                    code: e.target.value.toUpperCase().replace(/\s+/g, "_"),
                  }))
                }
                disabled={saving || Boolean(deptEditId)}
                className="w-full"
                placeholder="e.g. MR"
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
            <label>
              Plant
              <Dropdown
                value={deptForm.plantId || null}
                options={plantOptions}
                onChange={(e) => setDeptForm((f) => ({ ...f, plantId: e.value || "" }))}
                placeholder="Select plant"
                disabled={saving}
                className="w-full"
              />
            </label>
            <label>
              Sort order
              <SafeInputText
                profile="text"
                value={String(deptForm.sortOrder ?? 0)}
                onChange={(e) =>
                  setDeptForm((f) => ({
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
