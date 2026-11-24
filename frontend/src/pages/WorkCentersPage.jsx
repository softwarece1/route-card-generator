import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "primereact/button";
import { Dialog } from "primereact/dialog";
import { Message } from "primereact/message";
import { InputText } from "primereact/inputtext";
import { IconField } from "primereact/iconfield";
import { InputIcon } from "primereact/inputicon";
import SafeInputText from "@/components/SafeInputText";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import TableComponent from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { toast } from "@/lib/toast";
import { fetchSbus } from "@/services/authApi";
import {
  createWorkCenter,
  deleteWorkCenter,
  fetchPlants,
  fetchWorkCenters,
  syncWorkCentersFromSap,
  updateWorkCenter,
} from "@/services/routeCardApi";
import "./work-centers.scss";

const emptyWcForm = (plant) => ({
  code: "",
  name: "",
  plant: plant || "",
  sapCode: "",
  sortOrder: 0,
});

function formatSyncedAt(iso) {
  if (!iso) return { short: "Not synced", full: "Not synced yet" };
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { short: "Not synced", full: "Not synced yet" };
  return {
    short: `Synced ${d.toLocaleDateString()}`,
    full: `Last synced ${d.toLocaleString()}`,
  };
}

export default function WorkCentersPage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";
  const isSbuHead = user?.role === "sbu_head";
  const canManage = isAdmin || isSbuHead;

  const [sbus, setSbus] = useState([]);
  const [plants, setPlants] = useState([]);
  const [sbuSearch, setSbuSearch] = useState("");
  const [selectedSbuId, setSelectedSbuId] = useState(null);
  const [workCentres, setWorkCentres] = useState([]);
  const [wcSearch, setWcSearch] = useState("");
  const [loadingSbus, setLoadingSbus] = useState(false);
  const [loadingWc, setLoadingWc] = useState(false);
  const [wcRows, setWcRows] = useState(10);
  const [wcFirst, setWcFirst] = useState(0);

  const [wcDialog, setWcDialog] = useState({
    visible: false,
    mode: "create",
    form: emptyWcForm(""),
  });

  const [syncing, setSyncing] = useState(false);
  const [syncBanner, setSyncBanner] = useState(null);
  const [plantSbu, setPlantSbu] = useState({ items: [], loading: false, error: "" });
  const activePlant = useRef("");

  const plantByCode = useMemo(() => {
    const m = new Map();
    for (const p of plants) m.set(p.code, p);
    return m;
  }, [plants]);

  const loadSbus = useCallback(async () => {
    setLoadingSbus(true);
    try {
      const [sbuRes, plantRows] = await Promise.all([
        fetchSbus(),
        fetchPlants({ activeOnly: true }).catch(() => []),
      ]);
      const rows = sbuRes?.items || sbuRes || [];
      setSbus(
        (rows || []).map((x) => ({
          id: x.id ?? x.code ?? x.name,
          code: x.code || "",
          name: x.name || x.code || "",
          plantId: x.plantId || "",
          isActive: x.isActive !== false,
        }))
      );
      setPlants(plantRows || []);
    } catch (e) {
      toast.error(e.message || "Could not load SBUs");
      setSbus([]);
    } finally {
      setLoadingSbus(false);
    }
  }, []);

  useEffect(() => {
    loadSbus();
  }, [loadSbus]);

  const selectedSbu = useMemo(
    () => sbus.find((s) => s.id === selectedSbuId) || null,
    [sbus, selectedSbuId]
  );

  // Auto-select first SBU with a plant so work centres load on entry
  useEffect(() => {
    if (selectedSbuId != null) return;
    if (!sbus.length) return;
    let pool = sbus;
    if (!isAdmin && isSbuHead) {
      const mine = (user?.sbu || "").trim();
      const scoped = sbus.filter((s) => s.name === mine || s.code === mine);
      if (scoped.length) pool = scoped;
    }
    const withPlant = pool.find((s) => (s.plantId || "").trim());
    const pick = withPlant || pool[0];
    if (pick) setSelectedSbuId(pick.id);
  }, [sbus, selectedSbuId, isAdmin, isSbuHead, user?.sbu]);

  const selectedPlantCode = (selectedSbu?.plantId || "").trim();
  const selectedPlant = plantByCode.get(selectedPlantCode) || null;

  const loadWorkCentres = useCallback(async (plantCode) => {
    if (!plantCode) {
      setWorkCentres([]);
      return;
    }
    setLoadingWc(true);
    try {
      const rows = await fetchWorkCenters(undefined, { plant: plantCode });
      if (activePlant.current === plantCode) setWorkCentres(rows || []);
    } catch (e) {
      if (activePlant.current === plantCode) {
        toast.error(e.message || "Could not load work centres");
        setWorkCentres([]);
      }
    } finally {
      if (activePlant.current === plantCode) setLoadingWc(false);
    }
  }, []);

  useEffect(() => {
    activePlant.current = selectedPlantCode;
    setWcSearch("");
    setSyncBanner(null);
    setWcFirst(0);
    setWcRows(10);
    if (selectedPlantCode) {
      loadWorkCentres(selectedPlantCode);
    } else {
      setWorkCentres([]);
      setLoadingWc(false);
    }
  }, [selectedPlantCode, loadWorkCentres]);

  // Plant/SBU mapping comes from SAP Zppfm001 (intranet only). Do not auto-fetch
  // on plant select — that fails outside the plant network. Sync fills this table.
  useEffect(() => {
    setPlantSbu({ items: [], loading: false, error: "" });
  }, [selectedPlantCode]);

  const filteredSbus = useMemo(() => {
    let rows = sbus;
    if (!isAdmin && isSbuHead) {
      const mine = (user?.sbu || "").trim();
      rows = rows.filter((s) => s.name === mine || s.code === mine);
    }
    const q = sbuSearch.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((s) => {
      const blob = `${s.code} ${s.name} ${s.plantId}`.toLowerCase();
      return blob.includes(q);
    });
  }, [sbus, sbuSearch, isAdmin, isSbuHead, user?.sbu]);

  const filteredWorkCentres = useMemo(() => {
    const q = wcSearch.trim().toLowerCase();
    if (!q) return workCentres;
    return workCentres.filter((w) => {
      const blob = [w.code, w.name, w.sapCode, w.plant].join(" ").toLowerCase();
      return blob.includes(q);
    });
  }, [workCentres, wcSearch]);

  useEffect(() => {
    setWcFirst(0);
  }, [wcSearch]);

  if (!canManage) {
    return (
      <AppShell active="workcenters">
        <div className="rc-wc">
          <Message
            severity="warn"
            text="Only SBU heads and admins can manage work centres."
          />
        </div>
      </AppShell>
    );
  }

  const openCreateWc = () => {
    if (!selectedPlantCode) {
      toast.error("Set a plant code on this SBU before adding work centres");
      return;
    }
    setWcDialog({
      visible: true,
      mode: "create",
      form: emptyWcForm(selectedPlantCode),
    });
  };

  const openEditWc = (wc) => {
    setWcDialog({
      visible: true,
      mode: "edit",
      form: {
        id: wc.id,
        code: wc.code || "",
        name: wc.name || "",
        plant: wc.plant || selectedPlantCode,
        sapCode: wc.sapCode || "",
        sortOrder: wc.sortOrder || 0,
      },
    });
  };

  const saveWc = async () => {
    const f = wcDialog.form;
    const payload = {
      code: f.code,
      name: f.name,
      mode: "manual",
      plant: f.plant || selectedPlantCode,
      sapCode: f.sapCode || f.code,
      isShared: false,
      sbu: selectedSbu?.name || user?.sbu || "",
      sortOrder: Number(f.sortOrder) || 0,
      capabilityTags: [],
      matchKeywords: [String(f.code || "").trim()].filter(Boolean),
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
      await loadWorkCentres(selectedPlantCode);
    } catch (e) {
      toast.error(e.message || "Save failed");
    }
  };

  const runSapSync = async () => {
    if (!selectedPlantCode) {
      toast.error("Set a plant code on this SBU before syncing");
      return;
    }
    setSyncing(true);
    setSyncBanner({
      severity: "info",
      text: "Syncing work centres from SAP — this may take a while…",
    });
    try {
      const done = await syncWorkCentersFromSap({
        plantCode: selectedPlantCode,
        sbu: selectedSbu?.name || user?.sbu || "",
      });
      if (activePlant.current !== selectedPlantCode) return;
      setPlantSbu({ items: done?.plant_sbu || [], loading: false, error: "" });
      const created = done?.created_count ?? 0;
      const unique = done?.count ?? 0;
      const failed = done?.failed_work_centers_count ?? 0;
      setSyncBanner({
        severity: failed > 0 ? "warn" : "success",
        text:
          done?.message ||
          `Sync completed. ${unique} unique work centre(s); ${created} newly added.`,
      });
      if (failed > 0) toast.error(`Sync finished with ${failed} failed work centre(s)`);
      else toast.success("Plant/SBU mapping and work centre sync completed");
      await Promise.all([loadSbus(), loadWorkCentres(selectedPlantCode)]);
      // Refresh plant syncedAt from plants list
      const plantRows = await fetchPlants({ activeOnly: true }).catch(() => []);
      setPlants(plantRows || []);
    } catch (e) {
      if (activePlant.current !== selectedPlantCode) return;
      setSyncBanner({
        severity: "error",
        text: e.message || "SAP sync failed",
      });
      toast.error(e.message || "SAP sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const syncedLabel = formatSyncedAt(selectedPlant?.workCenterSyncedAt);

  const headerSubtitle = isAdmin
    ? "Select an SBU to browse local work centres. Sync from SAP needs the plant intranet."
    : selectedSbu
      ? selectedPlantCode
        ? `${selectedSbu.name} · Plant ${selectedPlantCode}`
        : `${selectedSbu.name} · No plant code set`
      : "Work centres for your SBU plant.";

  const wcToolbar = (
    <div className="rc-wc__header-tools">
      <IconField iconPosition="left" className="rc-wc__search">
        <InputIcon className="pi pi-search" />
        <InputText
          placeholder="Search work centres…"
          value={wcSearch}
          onChange={(e) => setWcSearch(e.target.value)}
          disabled={!selectedPlantCode}
        />
      </IconField>
      <div
        className="rc-wc__sync-group"
        title={`${syncedLabel.full}. SAP Zppfm001 is reachable on the plant intranet only.`}
      >
        <Button
          type="button"
          label="Sync from SAP"
          icon={syncing ? "pi pi-spin pi-spinner" : "pi pi-sync"}
          size="small"
          outlined
          disabled={syncing || !selectedPlantCode}
          onClick={runSapSync}
        />
        <span className="rc-wc__sync-chip">{syncedLabel.short}</span>
      </div>
      <Button
        type="button"
        label="Add work centre"
        icon="pi pi-building"
        size="small"
        disabled={syncing || !selectedPlantCode}
        onClick={openCreateWc}
      />
    </div>
  );

  return (
    <AppShell active="workcenters">
      <div className="rc-wc">
        <PageHeader
          title="Work centres"
          subtitle={headerSubtitle}
          icon="pi pi-building"
          actions={!isAdmin ? wcToolbar : undefined}
        />

        {syncBanner ? (
          <Message
            className="rc-wc__sync-banner mb-3 w-full"
            severity={syncBanner.severity}
            text={syncBanner.text}
          />
        ) : null}

        <div className={`rc-wc__layout${isAdmin ? "" : " rc-wc__layout--single"}`}>
          {isAdmin ? (
            <div className="rc-wc__shell rc-wc__sbu-pane">
              <div className="rc-wc__tabs-row">
                <div className="rc-wc__pane-title">SBUs</div>
                <div className="rc-wc__tabs-tools">
                  <IconField iconPosition="left" className="rc-wc__search">
                    <InputIcon className="pi pi-search" />
                    <InputText
                      placeholder="Search SBU…"
                      value={sbuSearch}
                      onChange={(e) => setSbuSearch(e.target.value)}
                    />
                  </IconField>
                </div>
              </div>
              <div className="rc-wc__panel">
                <TableComponent
                  className="rc-wc__sbu-table"
                  value={filteredSbus}
                  loading={loadingSbus}
                  dataKey="id"
                  paginator={filteredSbus.length > 10}
                  rows={10}
                  rowsPerPageOptions={[]}
                  pageLinkSize={2}
                  paginatorTemplate="PrevPageLink PageLinks NextPageLink"
                  emptyMessage="No SBUs found."
                  selectionMode="single"
                  selection={selectedSbu}
                  onSelectionChange={(e) => setSelectedSbuId(e.value?.id ?? null)}
                  onRowClick={(e) => setSelectedSbuId(e.data?.id ?? null)}
                  columns={[
                    { type: "index", header: "#", style: { width: "3rem" } },
                    {
                      type: "primarySub",
                      header: "SBU",
                      primary: (r) => r.name || "—",
                      secondary: (r) => r.code || "",
                    },
                    {
                      header: "Plant",
                      field: "plantId",
                      style: { width: "6.5rem" },
                      body: (r) => r.plantId || "—",
                    },
                  ]}
                />
              </div>
            </div>
          ) : null}

          <div className="rc-wc__shell rc-wc__detail-pane">
            {!selectedSbu ? (
              <div className="rc-wc__empty-detail">
                <Message
                  severity="info"
                  text={
                    isAdmin
                      ? "Select an SBU to view its work centres."
                      : loadingSbus
                        ? "Loading your SBU work centres…"
                        : "No plant is set for your SBU. Ask an admin to assign a plant ID."
                  }
                  className="w-full"
                />
              </div>
            ) : (
              <>
                {isAdmin ? (
                  <div className="rc-wc__tabs-row">
                    <div className="rc-wc__pane-title">
                      {selectedSbu.name}
                      <span className="rc-wc__pane-sub">
                        {selectedPlantCode
                          ? `Plant ${selectedPlantCode}`
                          : "No plant code set"}
                      </span>
                    </div>
                    <div className="rc-wc__tabs-tools">{wcToolbar}</div>
                  </div>
                ) : null}
                {selectedPlantCode ? (
                  <>
                    <div className="rc-wc__tabs-row">
                      <div className="rc-wc__pane-title">Unique Plant &amp; SBU mapping</div>
                    </div>
                    <div className="rc-wc__panel">
                      {plantSbu.error ? (
                        <Message severity="error" text={plantSbu.error} className="mb-3 w-full" />
                      ) : null}
                      <TableComponent
                        value={plantSbu.items.map((row) => ({ ...row, id: JSON.stringify(row) }))}
                        loading={plantSbu.loading}
                        dataKey="id"
                        paginator={plantSbu.items.length > 10}
                        rows={10}
                        emptyMessage={
                          plantSbu.error
                            ? "Plant/SBU mapping could not be loaded."
                            : "Click Sync from SAP on the plant network (intranet) to load Plant/SBU mapping."
                        }
                        columns={[
                          { field: "Plant ID", header: "Plant ID", sortable: true },
                          { field: "Plant Name", header: "Plant Name", sortable: true },
                          {
                            field: "SBU Co Code (with Location)",
                            header: "SBU Co Code (with Location)",
                            sortable: true,
                          },
                          { field: "SBU Name", header: "SBU Name", sortable: true },
                        ]}
                      />
                    </div>
                    <div className="rc-wc__tabs-row">
                      <div className="rc-wc__pane-title">Work centres</div>
                    </div>
                  </>
                ) : null}
                <div className="rc-wc__panel">
                  {!selectedPlantCode ? (
                    <Message
                      severity="warn"
                      className="w-full"
                      text="Plant ID is not set for this SBU. Ask an admin to assign it on the SBUs page."
                    />
                  ) : (
                    <TableComponent
                      value={filteredWorkCentres}
                      loading={loadingWc}
                      dataKey="id"
                      paginator
                      rows={wcRows}
                      first={wcFirst}
                      rowsPerPageOptions={[10, 25, 50, 100]}
                      onPage={(e) => {
                        setWcFirst(e.first ?? 0);
                        if (e.rows && e.rows !== wcRows) setWcRows(e.rows);
                      }}
                      emptyMessage={
                        wcSearch.trim()
                          ? "No work centres match your search."
                          : "No work centres for this plant yet."
                      }
                      columns={[
                        { type: "index", header: "#", style: { width: "3rem" } },
                        {
                          field: "code",
                          header: "Code",
                          sortable: true,
                          style: { width: "8rem" },
                        },
                        {
                          field: "name",
                          header: "Name",
                          sortable: true,
                        },
                        {
                          type: "actions",
                          header: "Actions",
                          style: { width: "7.5rem" },
                          renderActions: (row) => (
                            <>
                              <Button
                                type="button"
                                icon="pi pi-pencil"
                                rounded
                                text
                                size="small"
                                aria-label="Edit"
                                tooltip="Edit"
                                onClick={() => openEditWc(row)}
                              />
                              <Button
                                type="button"
                                icon="pi pi-trash"
                                rounded
                                text
                                size="small"
                                severity="danger"
                                aria-label="Delete"
                                tooltip="Deactivate"
                                onClick={async () => {
                                  try {
                                    await deleteWorkCenter(row.id);
                                    toast.success("Deactivated");
                                    loadWorkCentres(selectedPlantCode);
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
              </>
            )}
          </div>
        </div>

        <Dialog
          className="wc-dialog"
          header={wcDialog.mode === "create" ? "Add work centre" : "Edit work centre"}
          visible={wcDialog.visible}
          style={{ width: "min(26rem, 94vw)" }}
          modal
          onHide={() => setWcDialog((d) => ({ ...d, visible: false }))}
          footer={
            <div className="wc-dialog__footer">
              <Button
                type="button"
                label="Cancel"
                size="small"
                outlined
                onClick={() => setWcDialog((d) => ({ ...d, visible: false }))}
              />
              <Button type="button" label="Save" size="small" onClick={saveWc} />
            </div>
          }
        >
          <div className="wc-dialog__form">
            <div className="wc-dialog__row">
              <div className="wc-dialog__field">
                <label htmlFor="wc-code">Code</label>
                <SafeInputText
                  id="wc-code"
                  profile="text"
                  value={wcDialog.form.code}
                  onChange={(e) =>
                    setWcDialog((d) => ({
                      ...d,
                      form: { ...d.form, code: e.target.value.toUpperCase() },
                    }))
                  }
                />
              </div>
              <div className="wc-dialog__field">
                <label htmlFor="wc-plant">Plant</label>
                <SafeInputText
                  id="wc-plant"
                  profile="text"
                  value={wcDialog.form.plant}
                  disabled
                />
              </div>
            </div>
            <div className="wc-dialog__row wc-dialog__row--full">
              <div className="wc-dialog__field">
                <label htmlFor="wc-name">Name</label>
                <SafeInputText
                  id="wc-name"
                  profile="label"
                  value={wcDialog.form.name}
                  onChange={(e) =>
                    setWcDialog((d) => ({
                      ...d,
                      form: { ...d.form, name: e.target.value },
                    }))
                  }
                />
              </div>
            </div>
            <div className="wc-dialog__row">
              <div className="wc-dialog__field">
                <label htmlFor="wc-sap">SAP code</label>
                <SafeInputText
                  id="wc-sap"
                  profile="text"
                  value={wcDialog.form.sapCode}
                  onChange={(e) =>
                    setWcDialog((d) => ({
                      ...d,
                      form: { ...d.form, sapCode: e.target.value },
                    }))
                  }
                />
              </div>
              <div className="wc-dialog__field">
                <label htmlFor="wc-sort">Sort order</label>
                <SafeInputText
                  id="wc-sort"
                  profile="text"
                  value={String(wcDialog.form.sortOrder ?? 0)}
                  onChange={(e) =>
                    setWcDialog((d) => ({
                      ...d,
                      form: {
                        ...d.form,
                        sortOrder: e.target.value.replace(/\D/g, "").slice(0, 6) || "0",
                      },
                    }))
                  }
                />
              </div>
            </div>
          </div>
        </Dialog>
      </div>
    </AppShell>
  );
}
