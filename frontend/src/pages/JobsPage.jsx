import { useCallback, useEffect, useState } from "react";
import { Button } from "primereact/button";
import { DataTable } from "primereact/datatable";
import { Column } from "primereact/column";
import { Tag } from "primereact/tag";
import { useNavigate } from "react-router-dom";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import {toast} from "@/lib/toast";
import {
  cancelAnalyzeJob,
  fetchAnalyzeJobs,
  fetchQueueStats,
} from "@/services/routeCardApi";

function severityFor(status) {
  if (status === "done") return "success";
  if (status === "failed") return "danger";
  if (status === "running") return "info";
  if (status === "cancelled") return "warning";
  return "secondary";
}

export default function JobsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [jobs, q] = await Promise.all([
        fetchAnalyzeJobs({ mineOnly: true }),
        fetchQueueStats(),
      ]);
      setItems(jobs.items || []);
      setStats(q);
    } catch (e) {
      toast.error(e.message || "Could not load jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <AppShell active="jobs">
      <div className="rc-jobs">
        <PageHeader title="Analyze jobs" subtitle="Queue status and VLM lock (one vision job at a time)." />
        {stats && (
          <p style={{ color: "var(--pmf-text-muted)" }}>
            Queued: <strong>{stats.queued}</strong> · Running: <strong>{stats.running}</strong>
            {stats.vlmLocked ? " · VLM busy" : ""}
          </p>
        )}
        <DataTable value={items} loading={loading} size="small" emptyMessage="No jobs yet.">
          <Column field="id" header="Job" style={{ width: 80 }} />
          <Column field="sessionId" header="Session" />
          <Column
            field="status"
            header="Status"
            body={(r) => <Tag value={r.status} severity={severityFor(r.status)} />}
          />
          <Column field="progress" header="%" style={{ width: 60 }} />
          <Column field="message" header="Message" />
          <Column
            header=""
            body={(r) => (
              <div className="flex gap-1">
                <Button
                  type="button"
                  icon="pi pi-eye"
                  text
                  size="small"
                  onClick={() => navigate(`/generator?sessionId=${r.sessionId}`)}
                />
                {["queued", "running"].includes(r.status) && (
                  <Button
                    type="button"
                    icon="pi pi-times"
                    text
                    severity="danger"
                    size="small"
                    onClick={async () => {
                      await cancelAnalyzeJob(r.id);
                      load();
                    }}
                  />
                )}
              </div>
            )}
          />
        </DataTable>
      </div>
    </AppShell>
  );
}
