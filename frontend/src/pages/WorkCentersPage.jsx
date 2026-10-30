import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Dialog } from "primereact/dialog";
import { Dropdown } from "primereact/dropdown";
import { Checkbox } from "primereact/checkbox";
import { Message } from "primereact/message";
import { InputText } from "primereact/inputtext";
import { IconField } from "primereact/iconfield";
import { InputIcon } from "primereact/inputicon";
import SafeInputText from "@/components/SafeInputText";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import TableComponent, { TableStatusBadge } from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { toast } from "@/lib/toast";
import { fetchDepartments } from "@/services/authApi";
import {
  createMachine,
  createWorkCenter,
  deleteMachine,
  deleteWorkCenter,
  fetchPlants,
  fetchWorkCenters,
  syncWorkCentersFromSap,
  updateMachine,
  updateWorkCenter,
} from "@/services/routeCardApi";
import "./work-centers.scss";

function ymd(d) {
  if (!d) return "";
  const x = d instanceof Date ? d : new Date(d);
  if (Number.isNaN(x.getTime())) return "";
  const m = String(x.getMonth() + 1).padStart(2, "0");
  const day = String(x.getDate()).padStart(2, "0");
  return `${x.getFullYear()}-${m}-${day}`;
}

/** Default SAP sync window: last 1 year. */
function defaultSyncRange() {
  const to = new Date();
  const from = new Date();
  from.setFullYear(from.getFullYear() - 1);
  return { fromDate: ymd(from), toDate: ymd(to) };
}

function modeTone(mode) {
  const m = String(mode || "").toLowerCase();
  if (m === "manual") return "info";
  if (m === "machine") return "warn";
  if (m === "hybrid") return "success";
  return "neutral";
}

function modeLabel(mode) {
  const m = String(mode || "").toLowerCase();
  if (m === "manual") return "Manual";
  if (m === "machine") return "Machine";
  if (m === "hybrid") return "Hybrid";
  return mode || "—";
}

const MODE_OPTIONS = [
  { label: "Manual (manpower)", value: "manual" },
  { label: "Machine only", value: "machine" },
  { label: "Hybrid", value: "hybrid" },
];

const emptyWcForm = (dept) => ({
  code: "",
  name: "",
  mode: "hybrid",
  plant: "",
  sapCode: "",
  capabilityTags: "",
  matchKeywords: "",
  defaultTool: "",
  isShared: false,
  dept: dept || "",
  sortOrder: 0,
});

const emptyMachineForm = () => ({
  name: "",
  code: "",
  sapCode: "",
  description: "",
  capabilityTags: "",
  isManualPlaceholder: false,
  sortOrder: 0,
});

function tagsToStr(arr) {
  return Array.isArray(arr) ? arr.join(", ") : "";
}

function strToTags(s) {
  return String(s || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

export default function WorkCentersPage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";
  const isDeptHead = user?.role === "dept_head";
  const canManage = isAdmin || isDeptHead;

  const [items, setItems] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [plants, setPlants] = useState([]);
  const [filterDept, setFilterDept] = useState(isDeptHead ? user?.dept || "" : "");
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState(0);
  const [expandedRows, setExpandedRows] = useState(null);
  const [wcSearch, setWcSearch] = useState("");
  const [machineSearch, setMachineSearch] = useState("");
  const [addMachineWcId, setAddMachineWcId] = useState(null);

  const [wcDialog, setWcDialog] = useState({ visible: false, mode: "create", form: emptyWcForm() });
  const [mDialog, setMDialog] = useState({
    visible: false,
    mode: "create",
    form: emptyMachineForm(),
    machineId: null,
  });

  const [syncDialog, setSyncDialog] = useState({
    visible: false,
    plantCode: "",
  });
  const [syncing, setSyncing] = useState(false);
  const [syncBanner, setSyncBanner] = useState(null); // { severity, text }
  const [deptPlantId, setDeptPlantId] = useState(user?.plantId || "");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await fetchWorkCenters(filterDept || undefined);
      setItems(rows || []);
    } catch (e) {
      toast.error(e.message || "Could not load work centres");
    } finally {
      setLoading(false);
    }
  }, [filterDept]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    fetchDepartments()
      .then((d) => {
        const rows = d?.items || d || [];
        setDepartments(
          rows.map((x) => ({
            label: x.name || x.code,
            value: x.name || x.code,
            plantId: x.plantId || "",
          }))
        );
        if (!isAdmin) {
          const mine = rows.find(
            (x) => (x.name || x.code) === (user?.dept || "") || x.code === user?.dept
          );
          const pid = user?.plantId || mine?.plantId || "";
          if (pid) setDeptPlantId(pid);
        }
      })
      .catch(() => {});
  }, [isAdmin, user?.dept, user?.plantId]);

  useEffect(() => {
    if (!isAdmin) return;
    fetchPlants()
      .then((rows) =>
        setPlants(
          (rows || []).map((p) => ({
            label: p.label || `${p.code} — ${p.name}`,
            value: p.code,
          }))
        )
      )
      .catch(() => {});
  }, [isAdmin]);

  const filteredWorkcentres = useMemo(() => {
    const q = wcSearch.trim().toLowerCase();
    if (!q) return items;
    return items.filter((w) => {
      const blob = [
        w.code,
        w.name,
        w.mode,
        w.dept,
        w.plant,
        w.sapCode,
        ...(w.capabilityTags || []),
      ]
        .join(" ")
        .toLowerCase();
      return blob.includes(q);
    });
  }, [items, wcSearch]);

  const allMachines = useMemo(() => {
    const rows = [];
    for (const wc of items) {
      for (const m of wc.machines || []) {
        rows.push({
          ...m,
          workCenterCode: wc.code,
          workCenterName: wc.name,
          workCenterId: wc.id,
          workCenterMode: wc.mode,
        });
      }
    }
    return rows;
  }, [items]);

  const filteredMachines = useMemo(() => {
    const q = machineSearch.trim().toLowerCase();
    if (!q) return allMachines;
    return allMachines.filter((m) => {
      const blob = [m.name, m.code, m.sapCode, m.workCenterCode, m.workCenterName, m.description]
        .join(" ")
        .toLowerCase();
      return blob.includes(q);
    });
  }, [allMachines, machineSearch]);

  const wcOptionsForMachine = useMemo(
    () =>
      items
        .filter((w) => !(w.isShared && !isAdmin))
        .map((w) => ({
          label: `${w.code} — ${w.name}`,
          value: w.id,
        })),
    [items, isAdmin]
  );

  if (!canManage) {
    return (
      <AppShell active="workcenters">
        <div className="rc-wc">
          <Message severity="warn" text="Only department heads and admins can manage work centres." />
        </div>
      </AppShell>
    );
  }

  const openCreateWc = () => {
    setWcDialog({
      visible: true,
      mode: "create",
      form: emptyWcForm(isDeptHead ? user?.dept : filterDept || user?.dept),
    });
  };

  const runSapSync = async (plantCodeOverride) => {
    const range = defaultSyncRange();
    const plantCode = String(
      plantCodeOverride ?? (isAdmin ? syncDialog.plantCode : deptPlantId || user?.plantId) ?? ""
    ).trim();

    if (isAdmin && !plantCode) {
      toast.error("Select a plant");
      return;
    }
    if (!isAdmin && !plantCode) {
      toast.error("No plant configured for your department. Ask an admin to set plant_id.");
      return;
    }

    setSyncDialog((d) => ({ ...d, visible: false }));
    setSyncing(true);
    setSyncBanner({
      severity: "info",
      text: "Syncing work centres from SAP — data is being added and may take a while…",
    });

    try {
      const done = await syncWorkCentersFromSap(
        {
          plantCode: isAdmin ? plantCode : undefined,
          fromDate: range.fromDate,
          toDate: range.toDate,
          isShared: isAdmin,
          dept: isDeptHead ? user?.dept || "" : filterDept || user?.dept || "",
        },
        {
          onEvent: (evt) => {
            if (evt.type === "status" || evt.type === "progress") {
              setSyncBanner({
                severity: "info",
                text:
                  evt.message ||
                  "Syncing work centres from SAP — data is being added and may take a while…",
              });
            }
            if (evt.type === "work_center" && evt.item) {
              setItems((prev) => {
                const id = evt.item.id;
                if (prev.some((w) => w.id === id)) {
                  return prev.map((w) => (w.id === id ? { ...w, ...evt.item } : w));
                }
                return [...prev, evt.item];
              });
              setSyncBanner({
                severity: "info",
                text:
                  evt.message ||
                  `Found ${evt.uniqueCount || ""} unique work centre(s) — still scanning…`,
              });
            }
          },
        }
      );
      const created = done?.createdCount ?? 0;
      const unique = done?.uniqueCount ?? 0;
      setSyncBanner({
        severity: "success",
        text: `Sync completed. ${unique} unique work centre(s); ${created} newly added.`,
      });
      toast.success("Work centre sync completed");
      await load();
    } catch (e) {
      setSyncBanner({
        severity: "error",
        text: e.message || "SAP sync failed",
      });
      toast.error(e.message || "SAP sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const onSyncClick = () => {
    setSyncBanner(null);
    if (isAdmin) {
      setSyncDialog({
        visible: true,
        plantCode: syncDialog.plantCode || plants[0]?.value || "",
      });
      return;
    }
    // Dept heads: no prompt — plant from dept, dates default to 1 year
    runSapSync(deptPlantId || user?.plantId);
  };

  const openEditWc = (wc) => {
    setWcDialog({
      visible: true,
      mode: "edit",
      form: {
        id: wc.id,
        code: wc.code || "",
        name: wc.name || "",
        mode: wc.mode || "hybrid",
        plant: wc.plant || "",
        sapCode: wc.sapCode || "",
        capabilityTags: tagsToStr(wc.capabilityTags),
        matchKeywords: tagsToStr(wc.matchKeywords),
        defaultTool: wc.defaultTool || "",
        isShared: !!wc.isShared,
        dept: wc.dept || "",
        sortOrder: wc.sortOrder || 0,
      },
    });
  };

  const openAddMachine = (wc) => {
    setAddMachineWcId(wc?.id ?? null);
    setMDialog({
      visible: true,
      mode: "create",
      form: emptyMachineForm(),
      machineId: null,
    });
  };

  const openEditMachine = (m) => {
    setAddMachineWcId(m.workCenterId || m.work_center_id || null);
    setMDialog({
      visible: true,
      mode: "edit",
      machineId: m.id,
      form: {
        name: m.name || "",
        code: m.code || "",
        sapCode: m.sapCode || "",
        description: m.description || "",
        capabilityTags: tagsToStr(m.capabilityTags),
        isManualPlaceholder: !!m.isManualPlaceholder,
        sortOrder: m.sortOrder || 0,
      },
    });
  };

  const toggleExpand = (row) => {
    setExpandedRows((prev) => {
      const cur = prev && typeof prev === "object" ? { ...prev } : {};
      if (cur[row.id]) delete cur[row.id];
      else cur[row.id] = true;
      return cur;
    });
  };

  const saveWc = async () => {
    const f = wcDialog.form;
    const payload = {
      code: f.code,
      name: f.name,
      mode: f.mode,
      plant: f.plant,
      sapCode: f.sapCode,
      capabilityTags: strToTags(f.capabilityTags),
      matchKeywords: strToTags(f.matchKeywords),
      defaultTool: f.defaultTool,
      isShared: isAdmin ? !!f.isShared : false,
      dept: f.isShared ? "" : f.dept || user?.dept,
      sortOrder: Number(f.sortOrder) || 0,
    };
    try {
      if (wcDialog.mode === "create") {
        await createWorkCenter(payload);
        toast.success("Work centre created");
      } else {
        await updateWorkCenter(f.id, payload);
        toast.success("Work centre updated");
      }
      setWcDialog((d) => ({ ...d, visible: false }));
      await load();
    } catch (e) {
      toast.error(e.message || "Save failed");
    }
  };

  const saveMachine = async () => {
    const wcId = addMachineWcId;
    if (!wcId) {
      toast.warn("Select a work centre for this machine");
      return;
    }
    const f = mDialog.form;
    const payload = {
      workCenterId: wcId,
      name: f.name,
      code: f.code,
      sapCode: f.sapCode,
      description: f.description,
      capabilityTags: strToTags(f.capabilityTags),
      isManualPlaceholder: !!f.isManualPlaceholder,
      sortOrder: Number(f.sortOrder) || 0,
    };
    try {
      if (mDialog.mode === "create") {
        await createMachine(payload);
        toast.success("Machine added");
        setExpandedRows((prev) => ({ ...(prev || {}), [wcId]: true }));
      } else {
        await updateMachine(mDialog.machineId, payload);
        toast.success("Machine updated");
      }
      setMDialog((d) => ({ ...d, visible: false }));
      await load();
    } catch (e) {
      toast.error(e.message || "Save failed");
    }
  };

  const nestedMachinesTemplate = (row) => (
    <div className="rc-wc__nested" onClick={(e) => e.stopPropagation()}>
      <div className="rc-wc__nested-head">
        <span className="rc-wc__nested-title">Machines in {row.code}</span>
        <Button
          type="button"
          label="Add machine"
          icon="pi pi-plus"
          outlined
          size="small"
          disabled={row.isShared && !isAdmin}
          onClick={() => openAddMachine(row)}
        />
      </div>
      <TableComponent
        className="rc-table--nested"
        value={row.machines || []}
        dataKey="id"
        paginator={false}
        emptyMessage={
          row.mode === "manual" ? "Manual WC — machines optional." : "No machines on this work centre yet."
        }
        columns={[
          { type: "index", header: "#", style: { width: "3.25rem" } },
          {
            type: "primarySub",
            header: "Machine",
            primary: (m) => m.name || "—",
            secondary: (m) => m.code || m.sapCode || "",
          },
          {
            header: "Type",
            style: { width: "8.5rem" },
            body: (m) => (
              <TableStatusBadge
                value={m.isManualPlaceholder ? "Manpower" : "Machine"}
                tone={m.isManualPlaceholder ? "neutral" : "info"}
              />
            ),
          },
          {
            type: "actions",
            header: "Actions",
            style: { width: "7.5rem" },
            renderActions: (m) => (
              <>
                <Button
                  type="button"
                  icon="pi pi-pencil"
                  rounded
                  text
                  size="small"
                  aria-label="Edit"
                  tooltip="Edit"
                  onClick={() => openEditMachine({ ...m, workCenterId: row.id })}
                />
                <Button
                  type="button"
                  icon="pi pi-trash"
                  rounded
                  text
                  size="small"
                  severity="danger"
                  aria-label="Delete"
                  tooltip="Delete"
                  onClick={async () => {
                    try {
                      await deleteMachine(m.id);
                      toast.success("Deactivated");
                      load();
                    } catch (e) {
                      toast.error(e.message || "Delete failed");
                    }
                  }}
                />
              </>
            ),
          },
        ]}
      />
    </div>
  );

  const searchValue = activeTab === 0 ? wcSearch : machineSearch;
  const setSearchValue = activeTab === 0 ? setWcSearch : setMachineSearch;
  const searchPlaceholder =
    activeTab === 0 ? "Search workcentres..." : "Search machines...";

  return (
    <AppShell active="workcenters">
      <div className="rc-wc">
        <PageHeader
          title="Work centres"
          subtitle="Expand a work centre for its machines, or browse the full machines catalog."
          icon="pi pi-building"
          actions={
            <div className="flex gap-2 flex-wrap">
              {activeTab === 1 ? (
                <Button
                  type="button"
                  label="Add machine"
                  icon="pi pi-plus"
                  size="small"
                  onClick={() => openAddMachine(null)}
                />
              ) : (
                <>
                  <Button
                    type="button"
                    label="Sync work centre"
                    icon={syncing ? "pi pi-spin pi-spinner" : "pi pi-sync"}
                    size="small"
                    outlined
                    disabled={syncing}
                    onClick={onSyncClick}
                  />
                  <Button
                    type="button"
                    label="Add work centre"
                    icon="pi pi-building"
                    size="small"
                    disabled={syncing}
                    onClick={openCreateWc}
                  />
                </>
              )}
            </div>
          }
        />

        {syncBanner ? (
          <Message
            className="rc-wc__sync-banner mb-3 w-full"
            severity={syncBanner.severity}
            text={syncBanner.text}
          />
        ) : null}

        <div className="rc-wc__shell">
          <div className="rc-wc__tabs-row">
            <div className="rc-wc__tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 0}
                className={`rc-wc__tab${activeTab === 0 ? " is-active" : ""}`}
                onClick={() => setActiveTab(0)}
              >
                Workcentres
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 1}
                className={`rc-wc__tab${activeTab === 1 ? " is-active" : ""}`}
                onClick={() => setActiveTab(1)}
              >
                Machines
              </button>
            </div>
            <div className="rc-wc__tabs-tools">
              {isAdmin ? (
                <Dropdown
                  value={filterDept || null}
                  options={[{ label: "All / shared", value: "" }, ...departments]}
                  onChange={(e) => setFilterDept(e.value || "")}
                  placeholder="Filter department"
                  showClear
                  className="rc-wc__dept-filter"
                />
              ) : (
                <span className="rc-wc__dept-label">{user?.dept || "My department"}</span>
              )}
              <IconField iconPosition="left" className="rc-wc__search">
                <InputIcon className="pi pi-search" />
                <InputText
                  placeholder={searchPlaceholder}
                  value={searchValue}
                  onChange={(e) => setSearchValue(e.target.value)}
                />
              </IconField>
            </div>
          </div>

          <div className="rc-wc__panel">
            {activeTab === 0 ? (
              <TableComponent
                value={filteredWorkcentres}
                loading={loading}
                dataKey="id"
                paginator={filteredWorkcentres.length > 12}
                rows={12}
                emptyMessage="No work centres yet — seed defaults or add one."
                expandedRows={expandedRows}
                onRowToggle={(e) => setExpandedRows(e.data)}
                onRowClick={(e) => toggleExpand(e.data)}
                rowExpansionTemplate={nestedMachinesTemplate}
                columns={[
                  { type: "expander", style: { width: "3rem" } },
                  { type: "index", header: "#", style: { width: "3.25rem" } },
                  {
                    field: "code",
                    header: "Code",
                    sortable: true,
                    style: { width: "8rem" },
                  },
                  {
                    type: "primarySub",
                    header: "Work centre",
                    sortable: true,
                    field: "name",
                    primary: (r) => r.name || "—",
                    secondary: (r) =>
                      [r.isShared ? "Shared" : r.dept || "", r.sapCode ? `SAP ${r.sapCode}` : ""]
                        .filter(Boolean)
                        .join(" · "),
                  },
                  {
                    header: "Mode",
                    field: "mode",
                    sortable: true,
                    style: { width: "8.5rem" },
                    body: (r) => (
                      <TableStatusBadge value={modeLabel(r.mode)} tone={modeTone(r.mode)} />
                    ),
                  },
                  {
                    field: "plant",
                    header: "Plant",
                    sortable: true,
                    style: { width: "7.5rem" },
                    body: (r) => r.plant || "—",
                  },
                  {
                    header: "Machines",
                    style: { width: "7rem" },
                    body: (r) => (
                      <span className="rc-wc__count">{r.machines?.length || r.machineCount || 0}</span>
                    ),
                  },
                  {
                    type: "actions",
                    header: "Actions",
                    style: { width: "9.5rem" },
                    renderActions: (row) => (
                      <>
                        <Button
                          type="button"
                          icon="pi pi-plus"
                          rounded
                          text
                          size="small"
                          aria-label="Add machine"
                          tooltip="Add machine"
                          disabled={row.isShared && !isAdmin}
                          onClick={(e) => {
                            e.stopPropagation();
                            openAddMachine(row);
                          }}
                        />
                        <Button
                          type="button"
                          icon="pi pi-pencil"
                          rounded
                          text
                          size="small"
                          aria-label="Edit"
                          tooltip="Edit"
                          disabled={row.isShared && !isAdmin}
                          onClick={(e) => {
                            e.stopPropagation();
                            openEditWc(row);
                          }}
                        />
                        <Button
                          type="button"
                          icon="pi pi-trash"
                          rounded
                          text
                          size="small"
                          severity="danger"
                          aria-label="Delete"
                          tooltip="Delete"
                          disabled={row.isShared && !isAdmin}
                          onClick={async (e) => {
                            e.stopPropagation();
                            try {
                              await deleteWorkCenter(row.id);
                              toast.success("Deactivated");
                              load();
                            } catch (err) {
                              toast.error(err.message || "Delete failed");
                            }
                          }}
                        />
                      </>
                    ),
                  },
                ]}
              />
            ) : (
              <TableComponent
                value={filteredMachines}
                loading={loading}
                dataKey="id"
                paginator={filteredMachines.length > 12}
                rows={12}
                emptyMessage="No machines found."
                columns={[
                  { type: "index", header: "#", style: { width: "3.25rem" } },
                  {
                    type: "primarySub",
                    header: "Machine",
                    sortable: true,
                    field: "name",
                    primary: (m) => m.name || "—",
                    secondary: (m) => m.code || m.sapCode || "",
                  },
                  {
                    header: "Type",
                    style: { width: "8.5rem" },
                    body: (m) => (
                      <TableStatusBadge
                        value={m.isManualPlaceholder ? "Manpower" : "Machine"}
                        tone={m.isManualPlaceholder ? "neutral" : "info"}
                      />
                    ),
                  },
                  {
                    type: "primarySub",
                    header: "Work centre",
                    sortable: true,
                    sortField: "workCenterCode",
                    primary: (m) => m.workCenterCode || "—",
                    secondary: (m) => m.workCenterName || "",
                    style: { width: "12rem" },
                  },
                  {
                    field: "plant",
                    header: "Plant",
                    style: { width: "7.5rem" },
                    body: (m) => m.plant || "—",
                  },
                  {
                    type: "actions",
                    header: "Actions",
                    style: { width: "7.5rem" },
                    renderActions: (m) => (
                      <>
                        <Button
                          type="button"
                          icon="pi pi-pencil"
                          rounded
                          text
                          size="small"
                          aria-label="Edit"
                          tooltip="Edit"
                          onClick={() => openEditMachine(m)}
                        />
                        <Button
                          type="button"
                          icon="pi pi-trash"
                          rounded
                          text
                          size="small"
                          severity="danger"
                          aria-label="Delete"
                          tooltip="Delete"
                          onClick={async () => {
                            try {
                              await deleteMachine(m.id);
                              toast.success("Deactivated");
                              load();
                            } catch (e) {
                              toast.error(e.message || "Delete failed");
                            }
                          }}
                        />
                      </>
                    ),
                  },
                ]}
              />
            )}
          </div>
        </div>
      </div>

      <Dialog
        header={wcDialog.mode === "create" ? "Add work centre" : "Edit work centre"}
        visible={wcDialog.visible}
        onHide={() => setWcDialog((d) => ({ ...d, visible: false }))}
        style={{ width: "min(92vw, 28rem)" }}
        className="wc-dialog"
        footer={
          <div className="wc-dialog__footer">
            <Button
              type="button"
              label="Cancel"
              outlined
              size="small"
              onClick={() => setWcDialog((d) => ({ ...d, visible: false }))}
            />
            <Button type="button" label="Save" icon="pi pi-check" size="small" onClick={saveWc} />
          </div>
        }
      >
        <div className="wc-dialog__form">
          <div className="wc-dialog__row">
            <div className="wc-dialog__field">
              <label>Code</label>
              <SafeInputText
                profile="code"
                value={wcDialog.form.code}
                onChange={(e) =>
                  setWcDialog((d) => ({ ...d, form: { ...d.form, code: e.target.value } }))
                }
              />
            </div>
            <div className="wc-dialog__field">
              <label>Mode</label>
              <Dropdown
                value={wcDialog.form.mode}
                options={MODE_OPTIONS}
                onChange={(e) =>
                  setWcDialog((d) => ({ ...d, form: { ...d.form, mode: e.value } }))
                }
              />
            </div>
          </div>
          <div className="wc-dialog__row wc-dialog__row--full">
            <div className="wc-dialog__field">
              <label>Name</label>
              <SafeInputText
                profile="label"
                value={wcDialog.form.name}
                onChange={(e) =>
                  setWcDialog((d) => ({ ...d, form: { ...d.form, name: e.target.value } }))
                }
              />
            </div>
          </div>
          {isAdmin && (
            <div className="wc-dialog__row">
              <div className="wc-dialog__field">
                <label>Department</label>
                <Dropdown
                  value={wcDialog.form.dept || null}
                  options={departments}
                  disabled={wcDialog.form.isShared}
                  onChange={(e) =>
                    setWcDialog((d) => ({ ...d, form: { ...d.form, dept: e.value || "" } }))
                  }
                  placeholder="Department"
                />
              </div>
              <div className="wc-dialog__check">
                <Checkbox
                  inputId="wc-shared"
                  checked={!!wcDialog.form.isShared}
                  onChange={(e) =>
                    setWcDialog((d) => ({
                      ...d,
                      form: { ...d.form, isShared: e.checked, dept: e.checked ? "" : d.form.dept },
                    }))
                  }
                />
                <label htmlFor="wc-shared">Shared plant WC</label>
              </div>
            </div>
          )}
          <div className="wc-dialog__row">
            <div className="wc-dialog__field">
              <label>Plant</label>
              <SafeInputText
                profile="code"
                value={wcDialog.form.plant}
                onChange={(e) =>
                  setWcDialog((d) => ({ ...d, form: { ...d.form, plant: e.target.value } }))
                }
              />
            </div>
            <div className="wc-dialog__field">
              <label>SAP code</label>
              <SafeInputText
                profile="code"
                value={wcDialog.form.sapCode}
                onChange={(e) =>
                  setWcDialog((d) => ({ ...d, form: { ...d.form, sapCode: e.target.value } }))
                }
              />
            </div>
          </div>
          <div className="wc-dialog__row wc-dialog__row--full">
            <div className="wc-dialog__field">
              <label>Capability tags (comma)</label>
              <SafeInputText
                profile="text"
                value={wcDialog.form.capabilityTags}
                onChange={(e) =>
                  setWcDialog((d) => ({ ...d, form: { ...d.form, capabilityTags: e.target.value } }))
                }
                placeholder="torque, bonding, pcb, inspect"
              />
            </div>
          </div>
          <div className="wc-dialog__row wc-dialog__row--full">
            <div className="wc-dialog__field">
              <label>Match keywords (comma)</label>
              <SafeInputText
                profile="text"
                value={wcDialog.form.matchKeywords}
                onChange={(e) =>
                  setWcDialog((d) => ({ ...d, form: { ...d.form, matchKeywords: e.target.value } }))
                }
                placeholder="SOLDER, TORQUE, CLEAN"
              />
            </div>
          </div>
          <div className="wc-dialog__row wc-dialog__row--full">
            <div className="wc-dialog__field">
              <label>Default tool</label>
              <SafeInputText
                profile="text"
                value={wcDialog.form.defaultTool}
                onChange={(e) =>
                  setWcDialog((d) => ({ ...d, form: { ...d.form, defaultTool: e.target.value } }))
                }
              />
            </div>
          </div>
        </div>
      </Dialog>

      <Dialog
        header={mDialog.mode === "create" ? "Add machine" : "Edit machine"}
        visible={mDialog.visible}
        onHide={() => setMDialog((d) => ({ ...d, visible: false }))}
        style={{ width: "min(92vw, 26rem)" }}
        className="wc-dialog"
        footer={
          <div className="wc-dialog__footer">
            <Button
              type="button"
              label="Cancel"
              outlined
              size="small"
              onClick={() => setMDialog((d) => ({ ...d, visible: false }))}
            />
            <Button type="button" label="Save" icon="pi pi-check" size="small" onClick={saveMachine} />
          </div>
        }
      >
        <div className="wc-dialog__form">
          <div className="wc-dialog__row wc-dialog__row--full">
            <div className="wc-dialog__field">
              <label>Work centre</label>
              <Dropdown
                value={addMachineWcId}
                options={wcOptionsForMachine}
                onChange={(e) => setAddMachineWcId(e.value)}
                placeholder="Select work centre"
                filter
                disabled={mDialog.mode === "edit"}
              />
            </div>
          </div>
          <div className="wc-dialog__row wc-dialog__row--full">
            <div className="wc-dialog__field">
              <label>Name</label>
              <SafeInputText
                profile="label"
                value={mDialog.form.name}
                onChange={(e) =>
                  setMDialog((d) => ({ ...d, form: { ...d.form, name: e.target.value } }))
                }
              />
            </div>
          </div>
          <div className="wc-dialog__row">
            <div className="wc-dialog__field">
              <label>Code</label>
              <SafeInputText
                profile="code"
                value={mDialog.form.code}
                onChange={(e) =>
                  setMDialog((d) => ({ ...d, form: { ...d.form, code: e.target.value } }))
                }
              />
            </div>
            <div className="wc-dialog__field">
              <label>SAP code</label>
              <SafeInputText
                profile="code"
                value={mDialog.form.sapCode}
                onChange={(e) =>
                  setMDialog((d) => ({ ...d, form: { ...d.form, sapCode: e.target.value } }))
                }
              />
            </div>
          </div>
          <div className="wc-dialog__row wc-dialog__row--full">
            <div className="wc-dialog__field">
              <label>Description</label>
              <SafeInputText
                profile="text"
                value={mDialog.form.description}
                onChange={(e) =>
                  setMDialog((d) => ({ ...d, form: { ...d.form, description: e.target.value } }))
                }
              />
            </div>
          </div>
          <div className="wc-dialog__row wc-dialog__row--full">
            <div className="wc-dialog__field">
              <label>Capability tags (comma)</label>
              <SafeInputText
                profile="text"
                value={mDialog.form.capabilityTags}
                onChange={(e) =>
                  setMDialog((d) => ({ ...d, form: { ...d.form, capabilityTags: e.target.value } }))
                }
              />
            </div>
          </div>
          <div className="wc-dialog__check">
            <Checkbox
              inputId="m-manual"
              checked={!!mDialog.form.isManualPlaceholder}
              onChange={(e) =>
                setMDialog((d) => ({ ...d, form: { ...d.form, isManualPlaceholder: e.checked } }))
              }
            />
            <label htmlFor="m-manual">Manpower / bench placeholder</label>
          </div>
        </div>
      </Dialog>

      {isAdmin ? (
        <Dialog
          header="Sync work centres from SAP"
          visible={syncDialog.visible}
          onHide={() => !syncing && setSyncDialog((d) => ({ ...d, visible: false }))}
          style={{ width: "min(92vw, 24rem)" }}
          className="wc-dialog"
          footer={
            <div className="wc-dialog__footer">
              <Button
                type="button"
                label="Cancel"
                outlined
                size="small"
                disabled={syncing}
                onClick={() => setSyncDialog((d) => ({ ...d, visible: false }))}
              />
              <Button
                type="button"
                label="Start sync"
                icon="pi pi-sync"
                size="small"
                disabled={syncing || !syncDialog.plantCode}
                onClick={() => runSapSync(syncDialog.plantCode)}
              />
            </div>
          }
        >
          <p className="wc-dialog__hint" style={{ fontSize: "0.8rem", margin: "0 0 0.75rem" }}>
            Select a plant. Sync uses the last 1 year of production orders; rows appear as they are
            found.
          </p>
          <div className="wc-dialog__form">
            <div className="wc-dialog__row wc-dialog__row--full">
              <div className="wc-dialog__field">
                <label>Plant</label>
                <Dropdown
                  value={syncDialog.plantCode || null}
                  options={plants}
                  placeholder="Select plant"
                  filter
                  className="w-full"
                  onChange={(e) =>
                    setSyncDialog((d) => ({ ...d, plantCode: e.value || "" }))
                  }
                />
              </div>
            </div>
          </div>
        </Dialog>
      ) : null}
    </AppShell>
  );
}
