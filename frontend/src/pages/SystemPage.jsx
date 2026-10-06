import { useCallback, useEffect, useState } from "react";
import { Button } from "primereact/button";
import { DataTable } from "primereact/datatable";
import { Column } from "primereact/column";
import { InputText } from "primereact/inputtext";
import { InputNumber } from "primereact/inputnumber";
import { MultiSelect } from "primereact/multiselect";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import { toast } from "@/lib/toast";
import { getVlmPageIndexes, setVlmPageIndexes } from "@/lib/vlmPrefs";
import {
  createMachine,
  deleteMachine,
  fetchMachinesQuietly,
  fetchStorageStats,
  fetchSystemHealth,
  runAdminBackup,
  runAdminCleanup,
} from "@/services/routeCardApi";
import "./system.scss";

const VLM_PAGE_OPTIONS = Array.from({ length: 12 }, (_, i) => ({
  label: `Page ${i + 1}`,
  value: i + 1,
}));

export default function SystemPage() {
  const [health, setHealth] = useState(null);
  const [storage, setStorage] = useState(null);
  const [machines, setMachines] = useState([]);
  const [form, setForm] = useState({ name: "", workCentre: "", plant: "" });
  const [cleanupDays, setCleanupDays] = useState(90);
  const [busy, setBusy] = useState("");
  const [vlmPages, setVlmPages] = useState(() => getVlmPageIndexes());

  const load = useCallback(async () => {
    try {
      const [h, s, m] = await Promise.all([
        fetchSystemHealth(),
        fetchStorageStats(),
        fetchMachinesQuietly(),
      ]);
      setHealth(h);
      setStorage(s);
      setMachines(m || []);
    } catch (e) {
      toast.error(e.message || "Could not load system");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const saveVlmPrefs = () => {
    setVlmPageIndexes(vlmPages);
    toast.success(
      vlmPages?.length
        ? `VLM will use page(s): ${vlmPages.join(", ")}`
        : "VLM sheets set to Auto (all allowed pages)",
    );
  };

  return (
    <AppShell active="system">
      <div className="rc-system">
        <PageHeader
          title="System"
          subtitle="Health, analysis settings, storage, backup, and plant machines."
          icon="pi pi-cog"
          actions={
            <Button
              type="button"
              label="Refresh"
              icon="pi pi-refresh"
              size="small"
              outlined
              onClick={load}
            />
          }
        />

        <div className="rc-system__grid">
          <section className="rc-system__card">
            <div className="rc-system__card-head">
              <div>
                <h3>Health</h3>
                <p>Live status of services used by analyze jobs.</p>
              </div>
              <div className="rc-system__icon" aria-hidden>
                <i className="pi pi-heart" />
              </div>
            </div>
            {health ? (
              <div className="rc-system__metrics">
                <div className={`rc-system__metric ${health.status === "ok" ? "is-ok" : "is-bad"}`}>
                  <span className="label">API</span>
                  <span className="value">{health.status || "—"}</span>
                </div>
                <div className={`rc-system__metric ${health.postgres?.ok ? "is-ok" : "is-bad"}`}>
                  <span className="label">Postgres</span>
                  <span className="value">
                    {health.postgres?.ok ? "ok" : health.postgres?.error || "down"}
                  </span>
                </div>
                <div className={`rc-system__metric ${health.ollama?.ok ? "is-ok" : "is-bad"}`}>
                  <span className="label">Ollama</span>
                  <span className="value">
                    {health.ollama?.ok ? "ok" : health.ollama?.error || "unreachable"}
                  </span>
                </div>
                <div className="rc-system__metric">
                  <span className="label">VLM model</span>
                  <span className="value" style={{ fontSize: "0.78rem" }}>
                    {health.ollama?.model || "—"}
                  </span>
                </div>
                <div className="rc-system__metric">
                  <span className="label">Disk free</span>
                  <span className="value">
                    {health.disk?.freeBytes != null
                      ? `${(health.disk.freeBytes / 1e9).toFixed(1)} GB`
                      : health.disk?.error || "—"}
                  </span>
                </div>
                <div className="rc-system__metric">
                  <span className="label">Analyze queue</span>
                  <span className="value">
                    {health.queue?.queued ?? 0}q / {health.queue?.running ?? 0}r
                  </span>
                </div>
              </div>
            ) : (
              <p className="rc-system__hint">Loading health…</p>
            )}
          </section>

          <section className="rc-system__card">
            <div className="rc-system__card-head">
              <div>
                <h3>VLM sheets</h3>
                <p>Which drawing pages the vision model reads (Generator uses this).</p>
              </div>
              <div className="rc-system__icon" aria-hidden>
                <i className="pi pi-images" />
              </div>
            </div>
            <div className="rc-system__field" style={{ minWidth: 0 }}>
              <label htmlFor="vlm-pages">Pages (leave empty = Auto)</label>
              <MultiSelect
                inputId="vlm-pages"
                value={vlmPages}
                onChange={(e) => setVlmPages(e.value || [])}
                options={VLM_PAGE_OPTIONS}
                placeholder="Auto — all allowed pages"
                display="chip"
                className="w-full"
              />
            </div>
            <p className="rc-system__hint">
              Saved in this browser. Use Auto unless a drawing is huge and you only need certain sheets.
            </p>
            <div className="rc-system__actions">
              <Button type="button" label="Save VLM sheets" icon="pi pi-save" size="small" onClick={saveVlmPrefs} />
              <Button
                type="button"
                label="Reset to Auto"
                icon="pi pi-refresh"
                size="small"
                outlined
                severity="secondary"
                onClick={() => {
                  setVlmPages([]);
                  setVlmPageIndexes([]);
                  toast.info("VLM sheets reset to Auto");
                }}
              />
            </div>
          </section>

          <section className="rc-system__card">
            <div className="rc-system__card-head">
              <div>
                <h3>Storage</h3>
                <p>Upload root usage by department.</p>
              </div>
              <div className="rc-system__icon" aria-hidden>
                <i className="pi pi-database" />
              </div>
            </div>
            {storage ? (
              <>
                <p className="rc-system__hint">
                  Root: {storage.uploadRoot} · Total: {((storage.totalBytes || 0) / 1e6).toFixed(1)} MB
                </p>
                <DataTable value={storage.byDept || []} size="small" emptyMessage="No data">
                  <Column field="dept" header="Dept" />
                  <Column
                    field="bytes"
                    header="MB"
                    body={(r) => ((r.bytes || 0) / 1e6).toFixed(2)}
                  />
                </DataTable>
              </>
            ) : (
              <p className="rc-system__hint">Loading storage…</p>
            )}
          </section>

          <section className="rc-system__card">
            <div className="rc-system__card-head">
              <div>
                <h3>Backup &amp; cleanup</h3>
                <p>Export a backup or remove old draft route cards.</p>
              </div>
              <div className="rc-system__icon" aria-hidden>
                <i className="pi pi-download" />
              </div>
            </div>
            <div className="rc-system__actions">
              <Button
                type="button"
                label="Create backup"
                icon="pi pi-download"
                size="small"
                loading={busy === "backup"}
                onClick={async () => {
                  setBusy("backup");
                  try {
                    const r = await runAdminBackup();
                    toast.success(r.path ? `Backup: ${r.path}` : "Backup finished");
                  } catch (e) {
                    toast.error(e.message || "Backup failed");
                  } finally {
                    setBusy("");
                  }
                }}
              />
            </div>
            <div className="rc-system__actions">
              <div className="rc-system__field">
                <label htmlFor="cleanup-days">Drafts older than (days)</label>
                <InputNumber
                  inputId="cleanup-days"
                  value={cleanupDays}
                  onValueChange={(e) => setCleanupDays(e.value || 90)}
                  min={7}
                  showButtons
                />
              </div>
              <Button
                type="button"
                label="Preview cleanup"
                size="small"
                outlined
                onClick={async () => {
                  const r = await runAdminCleanup({ days: cleanupDays, dryRun: true });
                  toast.success(`Would delete ${r.count} draft route cards`);
                }}
              />
              <Button
                type="button"
                label="Run cleanup"
                size="small"
                severity="danger"
                outlined
                onClick={async () => {
                  const r = await runAdminCleanup({ days: cleanupDays, dryRun: false });
                  toast.success(`Deleted ${r.count} drafts`);
                  load();
                }}
              />
            </div>
          </section>

          <section className="rc-system__card rc-system__card--wide">
            <div className="rc-system__card-head">
              <div>
                <h3>Plant machines</h3>
                <p>Work-centre machines available when editing route operations.</p>
              </div>
              <div className="rc-system__icon" aria-hidden>
                <i className="pi pi-wrench" />
              </div>
            </div>
            <div className="rc-system__actions">
              <InputText
                placeholder="Name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
              <InputText
                placeholder="Work centre"
                value={form.workCentre}
                onChange={(e) => setForm({ ...form, workCentre: e.target.value })}
              />
              <InputText
                placeholder="Plant"
                value={form.plant}
                onChange={(e) => setForm({ ...form, plant: e.target.value })}
              />
              <Button
                type="button"
                label="Add"
                icon="pi pi-plus"
                size="small"
                onClick={async () => {
                  await createMachine(form);
                  setForm({ name: "", workCentre: "", plant: "" });
                  load();
                  toast.success("Machine added");
                }}
              />
            </div>
            <DataTable value={machines} size="small" emptyMessage="No machines">
              <Column field="name" header="Name" />
              <Column field="workCentre" header="WC" />
              <Column field="plant" header="Plant" />
              <Column
                header=""
                body={(r) => (
                  <Button
                    type="button"
                    icon="pi pi-trash"
                    text
                    severity="danger"
                    onClick={async () => {
                      await deleteMachine(r.id);
                      load();
                      toast.info("Machine removed");
                    }}
                  />
                )}
              />
            </DataTable>
          </section>
        </div>
      </div>
    </AppShell>
  );
}
