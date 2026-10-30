import { useCallback, useEffect, useState } from "react";
import { Button } from "primereact/button";
import { Message } from "primereact/message";
import SafeInputTextarea from "@/components/SafeInputTextarea";
import { toast } from "@/lib/toast";
import { createRouteRemark, fetchRouteRemarks } from "@/services/routeCardApi";
import "./route-remarks-panel.scss";

function roleShort(role) {
  if (role === "dept_head") return "Dept head";
  if (role === "ied") return "IED";
  if (role === "admin") return "Admin";
  return "Engineer";
}

export default function RouteRemarksPanel({ routeCardId, compact = false }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [posting, setPosting] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!routeCardId) {
      setItems([]);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await fetchRouteRemarks(routeCardId);
      setItems(res.items || []);
    } catch (err) {
      setItems([]);
      setError(err.message || "Could not load remarks");
    } finally {
      setLoading(false);
    }
  }, [routeCardId]);

  useEffect(() => {
    load();
  }, [load]);

  const post = async () => {
    const body = draft.trim();
    if (!body || !routeCardId) return;
    setPosting(true);
    setError("");
    try {
      const row = await createRouteRemark(routeCardId, body);
      setItems((prev) => [...prev, row]);
      setDraft("");
      toast.success("Remark posted.");
    } catch (err) {
      setError(err.message || "Could not post remark");
      toast.error(err.message || "Could not post remark");
    } finally {
      setPosting(false);
    }
  };

  if (!routeCardId) {
    return (
      <Message
        severity="info"
        className="w-full"
        text="Save a route card before posting remarks."
      />
    );
  }

  return (
    <div className={`rc-remarks${compact ? " rc-remarks--compact" : ""}`}>
      {error ? <Message severity="error" text={error} className="w-full mb-2" /> : null}
      <div className="rc-remarks__thread">
        {loading && items.length === 0 ? (
          <p className="rc-remarks__empty">Loading remarks…</p>
        ) : null}
        {!loading && items.length === 0 ? (
          <p className="rc-remarks__empty">
            No remarks yet. Engineers, dept heads, and IED can discuss here.
          </p>
        ) : null}
        {items.map((r) => (
          <article key={r.id} className="rc-remarks__item">
            <header className="rc-remarks__meta">
              <strong>
                {r.user?.name || r.user?.empId || "User"}
                {r.user?.role ? ` · ${roleShort(r.user.role)}` : ""}
              </strong>
              <time>
                {r.createdAt ? new Date(r.createdAt).toLocaleString() : ""}
              </time>
            </header>
            <p className="rc-remarks__body">{r.body}</p>
          </article>
        ))}
      </div>
      <div className="rc-remarks__composer">
        <SafeInputTextarea
          profile="remark"
          value={draft}
          rows={compact ? 2 : 3}
          className="w-full"
          maxLength={4000}
          placeholder="Add a remark for engineering / IED / dept head…"
          disabled={posting}
          onChange={(e) => setDraft(e.target.value)}
        />
        <Button
          type="button"
          label="Post remark"
          icon="pi pi-send"
          size="small"
          loading={posting}
          disabled={!draft.trim()}
          onClick={post}
        />
      </div>
    </div>
  );
}
