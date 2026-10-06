import { useEffect, useState } from "react";
import { Button } from "primereact/button";
import { InputText } from "primereact/inputtext";
import { InputTextarea } from "primereact/inputtextarea";
import { getUser } from "@/lib/auth";
import { toast } from "@/lib/toast";
import {
  createFewShot,
  deleteFewShot,
  fetchDeptRules,
  fetchFewShots,
  saveDeptRules,
} from "@/services/routeCardApi";

/** Dept-head / admin: auto-template ids, prompt addendum, few-shot bank. */
export default function DeptRulesPanel() {
  const user = getUser();
  const canEdit = user?.role === "admin" || user?.role === "dept_head";
  const [rules, setRules] = useState({
    autoTemplateIds: [],
    keywords: [],
    promptAddendum: "",
    wcAliases: {},
  });
  const [autoIds, setAutoIds] = useState("");
  const [keywords, setKeywords] = useState("");
  const [addendum, setAddendum] = useState("");
  const [examples, setExamples] = useState([]);
  const [exTitle, setExTitle] = useState("");
  const [exOut, setExOut] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [r, f] = await Promise.all([fetchDeptRules(), fetchFewShots()]);
        const rr = r.rules || {};
        setRules(rr);
        setAutoIds((rr.autoTemplateIds || []).join(", "));
        setKeywords((rr.keywords || []).join(", "));
        setAddendum(rr.promptAddendum || "");
        setExamples(f.items || []);
      } catch (e) {
        toast.error(e.message || "Could not load dept rules");
      }
    })();
  }, []);

  if (!canEdit) return null;

  return (
    <div className="p-3" style={{ maxWidth: 720 }}>
      <h3 style={{ marginTop: 0 }}>Department rules</h3>
      <p style={{ color: "var(--pmf-text-muted)", fontSize: "0.9rem" }}>
        Auto-apply operation template IDs on analyze (when keywords match), and add VLM prompt guidance.
      </p>
      <label className="block mb-2">Auto template IDs (comma-separated)</label>
      <InputText className="w-full mb-3" value={autoIds} onChange={(e) => setAutoIds(e.target.value)} />
      <label className="block mb-2">Keywords (comma-separated; empty = always)</label>
      <InputText className="w-full mb-3" value={keywords} onChange={(e) => setKeywords(e.target.value)} />
      <label className="block mb-2">VLM prompt addendum</label>
      <InputTextarea className="w-full mb-3" rows={4} value={addendum} onChange={(e) => setAddendum(e.target.value)} />
      <Button
        type="button"
        label="Save rules"
        icon="pi pi-save"
        className="mb-4"
        onClick={async () => {
          const next = {
            ...rules,
            autoTemplateIds: autoIds
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean)
              .map((x) => Number(x))
              .filter((n) => !Number.isNaN(n)),
            keywords: keywords
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean),
            promptAddendum: addendum,
          };
          await saveDeptRules({ dept: user.dept, rules: next });
          toast.success("Dept rules saved");
        }}
      />

      <h3>Few-shot elaborations</h3>
      <InputText
        className="w-full mb-2"
        placeholder="Title"
        value={exTitle}
        onChange={(e) => setExTitle(e.target.value)}
      />
      <InputTextarea
        className="w-full mb-2"
        rows={3}
        placeholder="Simple shop-floor wording (e.g. Stick Item 2 on DC OUT face. Keep 5 mm from top...)"
        value={exOut}
        onChange={(e) => setExOut(e.target.value)}
      />
      <Button
        type="button"
        label="Add example"
        icon="pi pi-plus"
        className="mb-3"
        onClick={async () => {
          await createFewShot({ title: exTitle, outputExcerpt: exOut, dept: user.dept });
          setExTitle("");
          setExOut("");
          const f = await fetchFewShots();
          setExamples(f.items || []);
          toast.success("Example added");
        }}
      />
      <ul>
        {examples.map((e) => (
          <li key={e.id} className="mb-2 flex justify-content-between gap-2">
            <span>
              <strong>{e.title}</strong> — {(e.outputExcerpt || "").slice(0, 120)}
            </span>
            <Button
              type="button"
              icon="pi pi-trash"
              text
              severity="danger"
              onClick={async () => {
                await deleteFewShot(e.id);
                const f = await fetchFewShots();
                setExamples(f.items || []);
              }}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
