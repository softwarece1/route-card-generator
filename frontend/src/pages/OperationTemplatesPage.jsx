import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Dialog } from "primereact/dialog";
import { Dropdown } from "primereact/dropdown";
import { InputText } from "primereact/inputtext";
import { InputTextarea } from "primereact/inputtextarea";
import { Message } from "primereact/message";
import { TabPanel, TabView } from "primereact/tabview";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import TableComponent, {
  TableActions,
  TableStatusBadge,
} from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { toast } from "@/lib/toast";
import { fetchDepartments } from "@/services/authApi";
import {
  createOperationTemplate,
  deleteOperationTemplate,
  duplicateOperationTemplate,
  getOperationTemplate,
  listOperationTemplates,
  updateOperationTemplate,
} from "@/services/routeCardApi";
import "./route-card-generation-alt.scss";
import "./operation-templates.scss";

const PLACEMENT_OPTIONS = [
  { label: "Before extracted ops (pre)", value: "pre" },
  { label: "After extracted ops (post)", value: "post" },
  { label: "Append / any", value: "any" },
];

const EMPTY_STEP = () => ({
  _key: `s-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
  operation: "",
  workCentre: "",
  setup: "1",
  time: "",
  instructionText: "",
  inspection: "",
  machine: "",
  tool: "",
  generates_output_serial: false,
  requires_input_material: false,
  manual_operation: true,
});

export default function OperationTemplatesPage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";
  const isDeptHead = user?.role === "dept_head";
  const canManage = isAdmin || isDeptHead;
  const isEngineer = !canManage;

  const [tab, setTab] = useState(0);
  const [ownItems, setOwnItems] = useState([]);
  const [otherItems, setOtherItems] = useState([]);
  const [adminItems, setAdminItems] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [adminDept, setAdminDept] = useState(null);
  const [otherDept, setOtherDept] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [viewTpl, setViewTpl] = useState(null);

  const [editor, setEditor] = useState({
    visible: false,
    mode: "create",
    id: null,
    name: "",
    description: "",
    placement: "any",
    dept: user?.dept || "",
    steps: [EMPTY_STEP()],
    saving: false,
  });

  const [dup, setDup] = useState({
    visible: false,
    source: null,
    name: "",
    saving: false,
  });

  const deptOptions = useMemo(
    () =>
      departments.map((d) => ({
        label: d.name || d.label,
        value: d.name || d.value,
      })),
    [departments],
  );

  const loadOwn = useCallback(async () => {
    const res = await listOperationTemplates({ scope: "own" });
    setOwnItems(res.items || []);
  }, []);

  const loadOther = useCallback(async () => {
    if (!isDeptHead && !isAdmin) return;
    const res = await listOperationTemplates({
      scope: "other",
      dept: otherDept || undefined,
    });
    setOtherItems(res.items || []);
  }, [isDeptHead, isAdmin, otherDept]);

  const loadAdmin = useCallback(async () => {
    if (!isAdmin) return;
    const res = await listOperationTemplates({
      scope: "all",
      dept: adminDept || undefined,
    });
    setAdminItems(res.items || []);
  }, [isAdmin, adminDept]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (isAdmin) {
        await loadAdmin();
      } else {
        await loadOwn();
        if (isDeptHead && tab === 1) await loadOther();
      }
    } catch (err) {
      setError(err.message || "Failed to load templates");
    } finally {
      setLoading(false);
    }
  }, [isAdmin, isDeptHead, loadAdmin, loadOwn, loadOther, tab]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await fetchDepartments();
        if (!cancelled) setDepartments(Array.isArray(rows) ? rows : []);
      } catch {
        if (!cancelled) setDepartments([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (tab === 1 && isDeptHead) {
      loadOther().catch((err) => setError(err.message || "Failed to load"));
    }
  }, [tab, isDeptHead, loadOther]);

  const openCreate = () => {
    setEditor({
      visible: true,
      mode: "create",
      id: null,
      name: "",
      description: "",
      placement: "any",
      dept: user?.dept || "",
      steps: [EMPTY_STEP()],
      saving: false,
    });
  };

  const openEdit = async (row) => {
    try {
      const full = await getOperationTemplate(row.id);
      setEditor({
        visible: true,
        mode: "edit",
        id: full.id,
        name: full.name || "",
        description: full.description || "",
        placement: full.placement || "any",
        dept: full.dept || "",
        steps: (full.steps || []).map((s) => ({
          ...EMPTY_STEP(),
          ...s,
          _key: `s-${s.id || Math.random()}`,
        })),
        saving: false,
      });
    } catch (err) {
      toast.error(err.message, "Load failed");
    }
  };

  const openView = async (row) => {
    try {
      const full = await getOperationTemplate(row.id);
      setViewTpl(full);
    } catch (err) {
      toast.error(err.message, "Load failed");
    }
  };

  const saveEditor = async () => {
    const name = editor.name.trim();
    if (!name) {
      toast.warn("Name required");
      return;
    }
    const steps = editor.steps
      .map(({ _key, ...rest }) => rest)
      .filter((s) => String(s.operation || "").trim());
    if (!steps.length) {
      toast.warn("Add at least one operation step");
      return;
    }
    setEditor((e) => ({ ...e, saving: true }));
    try {
      const payload = {
        name,
        description: editor.description,
        placement: editor.placement,
        steps,
      };
      if (editor.mode === "create") {
        if (isAdmin && editor.dept) payload.dept = editor.dept;
        await createOperationTemplate(payload);
      } else {
        await updateOperationTemplate(editor.id, payload);
      }
      setEditor((e) => ({ ...e, visible: false, saving: false }));
      toast.success(editor.mode === "create" ? "Template created" : "Template updated");
      await refresh();
    } catch (err) {
      setEditor((e) => ({ ...e, saving: false }));
      toast.error(err.message, "Save failed");
    }
  };

  const remove = async (row) => {
    if (!window.confirm(`Delete template "${row.name}"?`)) return;
    try {
      await deleteOperationTemplate(row.id);
      toast.success("Deleted");
      await refresh();
    } catch (err) {
      toast.error(err.message, "Delete failed");
    }
  };

  const openDup = (row) => {
    if (row.alreadyCopied) {
      toast.info("Already copied into your department");
      return;
    }
    setDup({
      visible: true,
      source: row,
      name: `${row.name} (copy)`,
      saving: false,
    });
  };

  const confirmDup = async () => {
    if (!dup.source) return;
    setDup((d) => ({ ...d, saving: true }));
    try {
      await duplicateOperationTemplate(dup.source.id, {
        name: dup.name.trim() || undefined,
      });
      setDup({ visible: false, source: null, name: "", saving: false });
      toast.success("Duplicated into your department");
      setTab(0);
      await refresh();
    } catch (err) {
      setDup((d) => ({ ...d, saving: false }));
      toast.error(err.message, "Duplicate failed");
    }
  };

  const updateStep = (key, field, value) => {
    setEditor((e) => ({
      ...e,
      steps: e.steps.map((s) => (s._key === key ? { ...s, [field]: value } : s)),
    }));
  };

  const addStep = () => {
    setEditor((e) => ({ ...e, steps: [...e.steps, EMPTY_STEP()] }));
  };

  const removeStep = (key) => {
    setEditor((e) => ({
      ...e,
      steps: e.steps.length <= 1 ? e.steps : e.steps.filter((s) => s._key !== key),
    }));
  };

  const moveStep = (key, dir) => {
    setEditor((e) => {
      const idx = e.steps.findIndex((s) => s._key === key);
      if (idx < 0) return e;
      const next = [...e.steps];
      const j = idx + dir;
      if (j < 0 || j >= next.length) return e;
      [next[idx], next[j]] = [next[j], next[idx]];
      return { ...e, steps: next };
    });
  };

  const pageDescription = isEngineer
    ? `View-only packs for ${user?.dept || "your department"}. Apply them from OARC preview.`
    : isAdmin
      ? "Manage packs across departments — filter by dept, create and edit."
      : "Create and edit packs for your team; browse other depts to duplicate.";

  const actionsCol = (row, { allowEdit }) => (
    <TableActions>
      {allowEdit ? (
        <>
          <Button
            type="button"
            icon="pi pi-pencil"
            rounded
            text
            size="small"
            aria-label="Edit"
            onClick={() => openEdit(row)}
          />
          <Button
            type="button"
            icon="pi pi-trash"
            rounded
            text
            size="small"
            severity="danger"
            aria-label="Delete"
            onClick={() => remove(row)}
          />
        </>
      ) : (
        <Button
          type="button"
          icon="pi pi-eye"
          rounded
          text
          size="small"
          aria-label="View"
          onClick={() => openView(row)}
        />
      )}
    </TableActions>
  );

  const templateColumns = ({ includeDept, allowEdit, otherDup }) => [
    { type: "index", header: "#", style: { width: "3.25rem" } },
    ...(includeDept
      ? [{ field: "dept", header: "Department", sortable: true, style: { width: "8rem" } }]
      : []),
    { field: "name", header: "Name", sortable: true },
    {
      header: "Steps",
      style: { width: "5rem" },
      sortable: true,
      field: "stepCount",
      body: (row) => row.stepCount ?? 0,
    },
    {
      header: "Placement",
      style: { width: "8rem" },
      body: (row) => (
        <TableStatusBadge value={row.placement || "any"} tone="info" />
      ),
    },
    ...(otherDup
      ? []
      : [
          {
            field: "description",
            header: "Description",
            body: (row) => row.description || "—",
          },
        ]),
    {
      header: "Actions",
      style: { width: otherDup ? "9rem" : "7.5rem" },
      body: (row) =>
        otherDup ? (
          <Button
            type="button"
            label={row.alreadyCopied ? "Copied" : "Duplicate"}
            icon={row.alreadyCopied ? "pi pi-check" : "pi pi-copy"}
            size="small"
            outlined={!row.alreadyCopied}
            disabled={Boolean(row.alreadyCopied)}
            tooltip={
              row.alreadyCopied
                ? "Already in your department — delete the copy first to duplicate again"
                : "Duplicate into my department"
            }
            tooltipOptions={{ position: "top" }}
            onClick={() => openDup(row)}
          />
        ) : (
          actionsCol(row, { allowEdit })
        ),
    },
  ];

  return (
    <AppShell active="templates">
      <div className="rc-otpl">
        <PageHeader
          title="Templates"
          subtitle={pageDescription}
          icon="pi pi-list"
          actions={
            canManage ? (
              <Button
                type="button"
                label="New template"
                icon="pi pi-plus"
                size="small"
                onClick={openCreate}
              />
            ) : null
          }
        />

        {error ? <Message severity="error" text={error} className="w-full mb-3" /> : null}

        {isAdmin ? (
          <>
            <div className="rc-otpl__other-bar">
              <Dropdown
                value={adminDept}
                options={[{ label: "All departments", value: null }, ...deptOptions]}
                onChange={(e) => setAdminDept(e.value)}
                placeholder="Filter department"
                className="rc-otpl__dept-filter"
                showClear
              />
              <Button
                type="button"
                label="Refresh"
                icon="pi pi-refresh"
                outlined
                size="small"
                onClick={() => loadAdmin().catch((err) => setError(err.message))}
              />
            </div>
            <TableComponent
              value={adminItems}
              loading={loading}
              dataKey="id"
              paginator
              rows={10}
              emptyMessage="No templates yet."
              columns={templateColumns({ includeDept: true, allowEdit: true })}
            />
          </>
        ) : isEngineer ? (
          <TableComponent
            value={ownItems}
            loading={loading}
            dataKey="id"
            paginator
            rows={10}
            emptyMessage="No templates in your department yet."
            columns={templateColumns({ includeDept: false, allowEdit: false })}
          />
        ) : (
          <TabView activeIndex={tab} onTabChange={(e) => setTab(e.index)}>
            <TabPanel header="My department">
              <TableComponent
                value={ownItems}
                loading={loading}
                dataKey="id"
                paginator
                rows={10}
                emptyMessage="No templates yet. Create a pack to get started."
                columns={templateColumns({ includeDept: false, allowEdit: true })}
              />
            </TabPanel>
            <TabPanel header="Other departments">
              <div className="rc-otpl__other-bar">
                <Dropdown
                  value={otherDept}
                  options={[{ label: "All other departments", value: null }, ...deptOptions]}
                  onChange={(e) => setOtherDept(e.value)}
                  placeholder="Filter department"
                  className="rc-otpl__dept-filter"
                  showClear
                />
                <Button
                  type="button"
                  label="Refresh"
                  icon="pi pi-refresh"
                  outlined
                  size="small"
                  onClick={() => loadOther().catch((err) => setError(err.message))}
                />
              </div>
              <TableComponent
                value={otherItems}
                loading={loading}
                dataKey="id"
                paginator
                rows={10}
                emptyMessage="No templates in other departments."
                columns={templateColumns({
                  includeDept: true,
                  allowEdit: false,
                  otherDup: true,
                })}
              />
            </TabPanel>
          </TabView>
        )}
      </div>

      <Dialog
        header={editor.mode === "create" ? "New operation template" : "Edit template"}
        visible={editor.visible}
        onHide={() => setEditor((e) => ({ ...e, visible: false }))}
        style={{ width: "min(44rem, 96vw)" }}
        className="rc-otpl-dialog"
        modal
        maximizable
        footer={
          <div className="rc-otpl-dialog__footer">
            <Button
              type="button"
              label="Cancel"
              outlined
              size="small"
              onClick={() => setEditor((e) => ({ ...e, visible: false }))}
            />
            <Button
              type="button"
              label="Save"
              icon="pi pi-check"
              size="small"
              loading={editor.saving}
              onClick={saveEditor}
            />
          </div>
        }
      >
        <div className="rc-otpl-form">
          <div className="rc-otpl-form__row">
            <label>Name *</label>
            <InputText
              value={editor.name}
              onChange={(e) => setEditor((x) => ({ ...x, name: e.target.value }))}
              className="w-full"
              placeholder="e.g. Pre-order kit checks"
            />
          </div>
          {isAdmin && editor.mode === "create" ? (
            <div className="rc-otpl-form__row">
              <label>Department</label>
              <Dropdown
                value={editor.dept}
                options={deptOptions}
                onChange={(e) => setEditor((x) => ({ ...x, dept: e.value }))}
                className="w-full"
                placeholder="Department"
              />
            </div>
          ) : null}
          <div className="rc-otpl-form__row">
            <label>Placement hint</label>
            <Dropdown
              value={editor.placement}
              options={PLACEMENT_OPTIONS}
              onChange={(e) => setEditor((x) => ({ ...x, placement: e.value }))}
              className="w-full"
            />
          </div>
          <div className="rc-otpl-form__row">
            <label>Description</label>
            <InputTextarea
              value={editor.description}
              onChange={(e) => setEditor((x) => ({ ...x, description: e.target.value }))}
              rows={2}
              className="w-full"
              autoResize
            />
          </div>
          <div className="rc-otpl-form__steps-head">
            <h4>Operations in this pack</h4>
            <Button
              type="button"
              label="Add step"
              icon="pi pi-plus"
              size="small"
              outlined
              onClick={addStep}
            />
          </div>
          {editor.steps.map((step, idx) => (
            <div key={step._key} className="rc-otpl-step">
              <div className="rc-otpl-step__bar">
                <span>Step {idx + 1}</span>
                <div className="rc-otpl__row-actions">
                  <Button
                    type="button"
                    icon="pi pi-arrow-up"
                    rounded
                    text
                    size="small"
                    disabled={idx === 0}
                    onClick={() => moveStep(step._key, -1)}
                  />
                  <Button
                    type="button"
                    icon="pi pi-arrow-down"
                    rounded
                    text
                    size="small"
                    disabled={idx === editor.steps.length - 1}
                    onClick={() => moveStep(step._key, 1)}
                  />
                  <Button
                    type="button"
                    icon="pi pi-trash"
                    rounded
                    text
                    size="small"
                    severity="danger"
                    disabled={editor.steps.length <= 1}
                    onClick={() => removeStep(step._key)}
                  />
                </div>
              </div>
              <div className="rc-otpl-step__grid">
                <div>
                  <label>Operation *</label>
                  <InputText
                    value={step.operation}
                    onChange={(e) => updateStep(step._key, "operation", e.target.value)}
                    className="w-full"
                    placeholder="Verification of kit"
                  />
                </div>
                <div>
                  <label>Work centre</label>
                  <InputText
                    value={step.workCentre}
                    onChange={(e) => updateStep(step._key, "workCentre", e.target.value)}
                    className="w-full"
                    placeholder="Assembly"
                  />
                </div>
                <div>
                  <label>Setup</label>
                  <InputText
                    value={step.setup}
                    onChange={(e) => updateStep(step._key, "setup", e.target.value)}
                    className="w-full"
                  />
                </div>
                <div>
                  <label>Per pc time</label>
                  <InputText
                    value={step.time}
                    onChange={(e) => updateStep(step._key, "time", e.target.value)}
                    className="w-full"
                  />
                </div>
                <div className="rc-otpl-step__full">
                  <label>Instruction (LongText)</label>
                  <InputTextarea
                    value={step.instructionText}
                    onChange={(e) => updateStep(step._key, "instructionText", e.target.value)}
                    rows={2}
                    className="w-full"
                    autoResize
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      </Dialog>

      <Dialog
        header="Duplicate into my department"
        visible={dup.visible}
        onHide={() => setDup({ visible: false, source: null, name: "", saving: false })}
        style={{ width: "min(28rem, 96vw)" }}
        className="rc-otpl-dialog"
        modal
        footer={
          <div className="rc-otpl-dialog__footer">
            <Button
              type="button"
              label="Cancel"
              outlined
              size="small"
              onClick={() => setDup({ visible: false, source: null, name: "", saving: false })}
            />
            <Button
              type="button"
              label="Duplicate"
              icon="pi pi-copy"
              size="small"
              loading={dup.saving}
              onClick={confirmDup}
            />
          </div>
        }
      >
        <p className="m-0 mb-3 text-sm" style={{ color: "#64748b" }}>
          Copying from {dup.source?.dept} / {dup.source?.name} into{" "}
          <strong>{user?.dept || "your department"}</strong>.
        </p>
        <label className="block mb-1 text-sm">New name</label>
        <InputText
          value={dup.name}
          onChange={(e) => setDup((d) => ({ ...d, name: e.target.value }))}
          className="w-full"
        />
      </Dialog>

      <Dialog
        header={viewTpl ? viewTpl.name : "Template"}
        visible={Boolean(viewTpl)}
        onHide={() => setViewTpl(null)}
        style={{ width: "min(40rem, 96vw)" }}
        className="rc-otpl-dialog"
        modal
        footer={
          <div className="rc-otpl-dialog__footer">
            <Button type="button" label="Close" size="small" onClick={() => setViewTpl(null)} />
          </div>
        }
      >
        {viewTpl ? (
          <div className="rc-otpl-form">
            <p className="m-0 text-sm" style={{ color: "#64748b" }}>
              Placement: <TableStatusBadge value={viewTpl.placement || "any"} tone="info" /> ·{" "}
              {(viewTpl.steps || []).length} step(s)
            </p>
            {(viewTpl.steps || []).map((s, i) => (
              <div key={s.id || i} className="rc-otpl-step">
                <div className="rc-otpl-step__bar">
                  <span>
                    {(i + 1) * 10}. {s.operation}
                  </span>
                </div>
                <p className="m-0 text-sm" style={{ color: "#475569" }}>
                  {s.workCentre ? `Wc: ${s.workCentre}` : ""}
                  {s.instructionText ? (
                    <>
                      <br />
                      {s.instructionText}
                    </>
                  ) : null}
                </p>
              </div>
            ))}
          </div>
        ) : null}
      </Dialog>
    </AppShell>
  );
}
