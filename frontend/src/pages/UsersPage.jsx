import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Dialog } from "primereact/dialog";
import { Dropdown } from "primereact/dropdown";
import SafeInputText from "@/components/SafeInputText";
import { Message } from "primereact/message";
import { Navigate } from "react-router-dom";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import TableComponent, { TableActions, TableStatusBadge } from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { sanitizeInput } from "@/lib/inputSafe";
import { generateCompliantPassword, getPasswordErrors } from "@/lib/passwordPolicy";
import { toast } from "@/lib/toast";
import { fetchDepartments } from "@/services/authApi";
import {
  createManagedUser,
  fetchAdminUsers,
  fetchDeptHeads,
  fetchDeptUsers,
  resetManagedUserPassword,
  updateManagedUser,
} from "@/services/routeCardApi";
import "./route-card-generation-alt.scss";
import "./users.scss";

/** PrimeReact Password can miss React state updates inside Dialogs; use plain input. */
function passwordValue(e) {
  const raw = e?.target?.value ?? e?.value ?? "";
  return sanitizeInput(raw, "password").value;
}

async function copyPasswordToClipboard(password) {
  const text = String(password || "");
  if (!text) throw new Error("Nothing to copy");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}

function TempPasswordField({
  label,
  value,
  onChange,
  show,
  onToggleShow,
  disabled,
  readOnly = false,
  placeholder,
  autoComplete = "new-password",
  headerExtra = null,
  showCopy = true,
}) {
  const copyPwd = async () => {
    try {
      await copyPasswordToClipboard(value);
      toast.success("Password copied — paste it to share with the employee");
    } catch {
      toast.error("Could not copy password");
    }
  };

  return (
    <label className="rc-users__pwd-field">
      <div className="rc-users__pwd-label-row">
        <span>{label}</span>
        <div className="rc-users__pwd-label-actions">{headerExtra}</div>
      </div>
      <div className="rc-users__pwd-input-row">
        <SafeInputText
          profile="password"
          type={show ? "text" : "password"}
          value={value}
          onChange={onChange || (() => {})}
          disabled={disabled}
          readOnly={readOnly}
          autoComplete={autoComplete}
          placeholder={placeholder}
          className="w-full"
        />
        <Button
          type="button"
          icon={show ? "pi pi-eye-slash" : "pi pi-eye"}
          rounded
          text
          size="small"
          className="rc-users__pwd-icon-btn"
          disabled={disabled || !value}
          onClick={onToggleShow}
          aria-label={show ? "Hide password" : "Show password"}
          tooltip={show ? "Hide" : "Show"}
          tooltipOptions={{ position: "top" }}
        />
        {showCopy ? (
          <Button
            type="button"
            icon="pi pi-copy"
            rounded
            text
            size="small"
            className="rc-users__pwd-icon-btn"
            disabled={disabled || !value}
            onClick={copyPwd}
            aria-label="Copy password"
            tooltip="Copy"
            tooltipOptions={{ position: "top" }}
          />
        ) : null}
      </div>
    </label>
  );
}

const EMP_ID_DIGITS = /^\d{6}$/;

function isValidEmployeeId(value) {
  return EMP_ID_DIGITS.test(String(value || "").trim());
}

const ROLE_OPTIONS_ADMIN = [
  { label: "Engineer", value: "engineer" },
  { label: "Dept head", value: "dept_head" },
  { label: "IED", value: "ied" },
];

const ROLE_OPTIONS_DEPT_HEAD = [{ label: "Engineer", value: "engineer" }];

function roleTone(role) {
  if (role === "admin") return "danger";
  if (role === "dept_head") return "info";
  if (role === "ied") return "success";
  return "neutral";
}

function roleLabel(role) {
  if (role === "admin") return "Admin";
  if (role === "dept_head") return "Dept head";
  if (role === "ied") return "IED";
  return "Engineer";
}

const emptyCreate = () => ({
  empId: "",
  name: "",
  dept: "",
  role: "engineer",
  reportsToId: null,
  password: "",
  confirmPassword: "",
});

const emptyEdit = () => ({
  empId: "",
  name: "",
  dept: "",
  role: "engineer",
  reportsToId: null,
});

export default function UsersPage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";
  const isDeptHead = user?.role === "dept_head";

  const [users, setUsers] = useState([]);
  const [dept, setDept] = useState("");
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState(emptyCreate);

  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [editForm, setEditForm] = useState(emptyEdit);

  const [resetOpen, setResetOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetConfirm, setResetConfirm] = useState("");
  const [resetShowPwd, setResetShowPwd] = useState(false);
  const [resetShareReady, setResetShareReady] = useState(false);
  const [createShowPwd, setCreateShowPwd] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [headOptions, setHeadOptions] = useState([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = isAdmin ? await fetchAdminUsers() : await fetchDeptUsers();
      setUsers(res.users || []);
      setDept(res.dept || user?.dept || "");
    } catch (err) {
      setUsers([]);
      setError(err.message || "Could not load users");
    } finally {
      setLoading(false);
    }
  }, [isAdmin, user?.dept]);

  useEffect(() => {
    if (isAdmin || isDeptHead) load();
  }, [isAdmin, isDeptHead, load]);

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    fetchDepartments()
      .then((rows) => {
        if (!cancelled) setDepartments(Array.isArray(rows) ? rows : []);
      })
      .catch(() => {
        if (!cancelled) setDepartments([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  const deptOptions = useMemo(
    () =>
      departments.map((d) => ({
        label: d.label || d.name,
        value: d.name || d.value,
      })),
    [departments]
  );

  const canManageRow = (row) => {
    if (!row || row.role === "admin") return false;
    if (isAdmin) return true;
    if (isDeptHead) return row.role === "engineer";
    return false;
  };

  const loadHeads = useCallback(async (deptName) => {
    const d = (deptName || "").trim();
    if (!d) {
      setHeadOptions([]);
      return;
    }
    try {
      const items = await fetchDeptHeads(d);
      setHeadOptions(
        (items || []).map((h) => ({
          label: h.label || `${h.name} (${h.empId})`,
          value: h.id,
        })),
      );
    } catch {
      setHeadOptions([]);
    }
  }, []);

  const openCreate = () => {
    const deptVal = isAdmin ? "" : user?.dept || "";
    setCreateForm({
      ...emptyCreate(),
      dept: deptVal,
      role: "engineer",
      reportsToId: isDeptHead ? user?.id || null : null,
    });
    setCreateShowPwd(false);
    setDialogError("");
    setCreateOpen(true);
    if (deptVal) loadHeads(deptVal);
    else setHeadOptions([]);
  };

  const closeResetDialog = () => {
    if (saving) return;
    setResetOpen(false);
    setResetTarget(null);
    setResetPassword("");
    setResetConfirm("");
    setResetShowPwd(false);
    setResetShareReady(false);
    setDialogError("");
  };

  const openEdit = (row) => {
    setEditTarget(row);
    setEditForm({
      empId: row.empId || "",
      name: row.name || "",
      dept: row.dept || "",
      role: row.role === "admin" ? "engineer" : row.role,
      reportsToId: row.reportsToId || null,
    });
    setDialogError("");
    setEditOpen(true);
    if (row.dept) loadHeads(row.dept);
    else setHeadOptions([]);
  };

  const openReset = (row) => {
    setResetTarget(row);
    setResetPassword("");
    setResetConfirm("");
    setResetShowPwd(false);
    setResetShareReady(false);
    setDialogError("");
    setResetOpen(true);
  };

  const saveCreate = async () => {
    const empId = createForm.empId.trim();
    const name = createForm.name.trim();
    if (!empId || !name) {
      setDialogError("Employee ID and name are required");
      return;
    }
    if (!isValidEmployeeId(empId)) {
      setDialogError("Employee ID must be exactly 6 digits");
      return;
    }
    const pwdErrors = getPasswordErrors(createForm.password);
    if (pwdErrors.length > 0) {
      setDialogError(`Password requirements: ${pwdErrors[0]}`);
      return;
    }
    if (createForm.password !== createForm.confirmPassword) {
      setDialogError("Passwords do not match");
      return;
    }
    if (isAdmin && !createForm.dept) {
      setDialogError("Select a department");
      return;
    }
    const role = isAdmin ? createForm.role : "engineer";
    if (role === "engineer" && !createForm.reportsToId) {
      setDialogError("Select a reporting officer (department head)");
      return;
    }
    setSaving(true);
    setDialogError("");
    setError("");
    try {
      await createManagedUser({
        empId,
        name,
        dept: isAdmin ? createForm.dept : undefined,
        role,
        password: createForm.password,
        reportsToId: role === "engineer" ? createForm.reportsToId : undefined,
      });
      setCreateOpen(false);
      toast.success(`User ${empId} created`);
      await load();
    } catch (err) {
      setDialogError(err.message || "Could not create user");
    } finally {
      setSaving(false);
    }
  };

  const saveEdit = async () => {
    if (!editTarget?.id) return;
    const empId = editForm.empId.trim();
    const name = editForm.name.trim();
    if (!empId || !name) {
      setDialogError("Employee ID and name are required");
      return;
    }
    if (!isValidEmployeeId(empId)) {
      setDialogError("Employee ID must be exactly 6 digits");
      return;
    }
    if (isAdmin && !editForm.dept) {
      setDialogError("Select a department");
      return;
    }
    const role = isAdmin ? editForm.role : editTarget.role;
    if (role === "engineer" && !editForm.reportsToId) {
      setDialogError("Select a reporting officer (department head)");
      return;
    }
    setSaving(true);
    setDialogError("");
    setError("");
    try {
      const payload = { empId, name };
      if (isAdmin) {
        payload.dept = editForm.dept;
        payload.role = editForm.role;
      }
      if (role === "engineer") {
        payload.reportsToId = editForm.reportsToId;
      }
      const updated = await updateManagedUser(editTarget.id, payload);
      setUsers((list) =>
        list.map((u) =>
          u.id === updated.id
            ? {
                ...u,
                empId: updated.empId,
                name: updated.name,
                dept: updated.dept,
                role: updated.role,
                reportsToId: updated.reportsToId,
                reportsToName: updated.reportsToName,
                reportsToEmpId: updated.reportsToEmpId,
              }
            : u
        )
      );
      setEditOpen(false);
      setEditTarget(null);
      toast.success("User updated");
    } catch (err) {
      setDialogError(err.message || "Could not update user");
    } finally {
      setSaving(false);
    }
  };

  const saveReset = async () => {
    if (!resetTarget?.id || resetShareReady) return;
    const pwdErrors = getPasswordErrors(resetPassword);
    if (pwdErrors.length > 0) {
      setDialogError(`Password requirements: ${pwdErrors[0]}`);
      return;
    }
    if (resetPassword !== resetConfirm) {
      setDialogError("Passwords do not match");
      return;
    }
    setSaving(true);
    setDialogError("");
    setError("");
    try {
      const res = await resetManagedUserPassword(resetTarget.id, resetPassword);
      setResetShowPwd(true);
      setResetShareReady(true);
      try {
        await copyPasswordToClipboard(resetPassword);
        toast.success(
          `Password reset for ${res.empId || resetTarget.empId}. Copied — share it with the employee now.`
        );
      } catch {
        toast.success(
          `Password reset for ${res.empId || resetTarget.empId}. Copy it below and share with the employee.`
        );
      }
    } catch (err) {
      setDialogError(err.message || "Could not reset password");
    } finally {
      setSaving(false);
    }
  };

  const pageDescription = useMemo(() => {
    if (isAdmin) {
      return "Add department heads, engineers, or IED users; assign reporting officers; reset passwords.";
    }
    if (isDeptHead) {
      return dept
        ? `Manage your direct reports in ${dept} — add engineers, edit details, and reset passwords.`
        : "Manage your direct-report engineers — add users, edit details, and reset passwords.";
    }
    return "";
  }, [isAdmin, isDeptHead, dept]);

  if (!isAdmin && !isDeptHead) {
    return <Navigate to="/generator" replace />;
  }

  return (
    <AppShell active="users">
      <div className="rc-users">
        <PageHeader
          title="Users"
          subtitle={pageDescription}
          icon="pi pi-users"
          actions={
            <>
              <Button
                type="button"
                label="Refresh"
                icon="pi pi-refresh"
                size="small"
                outlined
                onClick={() => load()}
              />
              <Button
                type="button"
                label={isAdmin ? "Add user" : "Add user"}
                icon="pi pi-user-plus"
                size="small"
                onClick={openCreate}
              />
            </>
          }
        />
        {error ? <Message severity="error" text={error} className="w-full mb-3" /> : null}

        <TableComponent
          value={users}
          loading={loading}
          dataKey="id"
          paginator
          rows={12}
          emptyMessage="No users found."
          columns={[
            { type: "index", header: "#", style: { width: "3.25rem" } },
            { field: "empId", header: "Emp ID", sortable: true, style: { width: "8.5rem" } },
            { field: "name", header: "Name", sortable: true },
            ...(isAdmin
              ? [{ field: "dept", header: "Department", sortable: true, style: { width: "9rem" } }]
              : []),
            {
              header: "Role",
              style: { width: "8rem" },
              body: (row) => (
                <TableStatusBadge value={roleLabel(row.role)} tone={roleTone(row.role)} />
              ),
            },
            {
              header: "Reports to",
              style: { width: "10rem" },
              body: (row) =>
                row.reportsToName
                  ? `${row.reportsToName}`
                  : row.role === "engineer"
                    ? "—"
                    : "—",
            },
            {
              header: "Sessions",
              style: { width: "7rem" },
              sortable: true,
              field: "sessionCount",
              body: (row) => row.sessionCount ?? 0,
            },
            {
              header: "Extractions",
              style: { width: "8rem" },
              sortable: true,
              field: "analyzedCount",
              body: (row) => row.analyzedCount ?? 0,
            },
            {
              header: "Actions",
              style: { width: "7.5rem" },
              body: (row) => {
                if (!canManageRow(row)) return "—";
                return (
                  <TableActions>
                    <Button
                      type="button"
                      icon="pi pi-pencil"
                      rounded
                      text
                      size="small"
                      aria-label="Edit"
                      tooltip="Edit"
                      tooltipOptions={{ position: "top" }}
                      onClick={() => openEdit(row)}
                    />
                    <Button
                      type="button"
                      icon="pi pi-key"
                      rounded
                      text
                      size="small"
                      aria-label="Reset password"
                      tooltip="Reset password"
                      tooltipOptions={{ position: "top" }}
                      onClick={() => openReset(row)}
                    />
                  </TableActions>
                );
              },
            },
          ]}
        />

        <Dialog
          header="Add user"
          visible={createOpen}
          style={{ width: "min(36rem, 94vw)" }}
          className="rc-users-dialog"
          modal
          onHide={() => !saving && setCreateOpen(false)}
          footer={
            <div className="rc-users__dialog-footer">
              <Button
                type="button"
                label="Cancel"
                outlined
                size="small"
                disabled={saving}
                onClick={() => setCreateOpen(false)}
              />
              <Button
                type="button"
                label="Save"
                icon="pi pi-check"
                size="small"
                loading={saving}
                onClick={saveCreate}
              />
            </div>
          }
        >
          {dialogError ? (
            <Message severity="error" text={dialogError} className="w-full mb-2" />
          ) : null}
          <div className="rc-users__form rc-users__form--grid">
            <label>
              Emp ID (6 digits)
              <SafeInputText
                profile="empId"
                value={createForm.empId}
                onChange={(e) =>
                  setCreateForm((f) => ({
                    ...f,
                    empId: e.target.value.replace(/\D/g, "").slice(0, 6),
                  }))
                }
                disabled={saving}
                autoComplete="off"
                inputMode="numeric"
                maxLength={6}
                placeholder="e.g. 112233"
              />
            </label>
            <label>
              Name
              <SafeInputText
                profile="personName"
                value={createForm.name}
                onChange={(e) => setCreateForm((f) => ({ ...f, name: e.target.value }))}
                disabled={saving}
              />
            </label>
            {isAdmin ? (
              <label>
                Department
                <Dropdown
                  value={createForm.dept || null}
                  options={deptOptions}
                  onChange={(e) => {
                    const next = e.value || "";
                    setCreateForm((f) => ({
                      ...f,
                      dept: next,
                      reportsToId: null,
                    }));
                    loadHeads(next);
                  }}
                  placeholder="Select department"
                  disabled={saving || deptOptions.length === 0}
                  className="w-full"
                />
              </label>
            ) : (
              <label>
                Department
                <SafeInputText profile="text" value={user?.dept || dept || ""} disabled />
              </label>
            )}
            <label>
              Role
              <Dropdown
                value={createForm.role}
                options={isAdmin ? ROLE_OPTIONS_ADMIN : ROLE_OPTIONS_DEPT_HEAD}
                onChange={(e) =>
                  setCreateForm((f) => ({
                    ...f,
                    role: e.value,
                    reportsToId:
                      e.value === "engineer"
                        ? f.reportsToId || (isDeptHead ? user?.id : null)
                        : null,
                  }))
                }
                disabled={saving}
                className="w-full"
              />
            </label>
            {createForm.role === "engineer" ? (
              <label>
                Reporting officer
                <Dropdown
                  value={createForm.reportsToId}
                  options={headOptions}
                  onChange={(e) =>
                    setCreateForm((f) => ({ ...f, reportsToId: e.value || null }))
                  }
                  placeholder={
                    headOptions.length ? "Select dept head" : "No dept heads in this dept"
                  }
                  disabled={saving || headOptions.length === 0}
                  className="w-full"
                />
              </label>
            ) : null}
            <TempPasswordField
              label="Temporary password"
              value={createForm.password}
              onChange={(e) =>
                setCreateForm((f) => ({ ...f, password: passwordValue(e) }))
              }
              show={createShowPwd}
              onToggleShow={() => setCreateShowPwd((v) => !v)}
              disabled={saving}
              placeholder="At least 12 chars (upper, lower, digit, special)"
              headerExtra={
                <Button
                  type="button"
                  label="Auto-generate"
                  icon="pi pi-sparkles"
                  size="small"
                  text
                  className="p-0 text-xs"
                  onClick={() => {
                    const generated = generateCompliantPassword();
                    setCreateForm((f) => ({
                      ...f,
                      password: generated,
                      confirmPassword: generated,
                    }));
                    setCreateShowPwd(true);
                    toast.info("Generated — use Show/Copy to share with the employee");
                  }}
                />
              }
            />
            <TempPasswordField
              label="Confirm password"
              value={createForm.confirmPassword}
              onChange={(e) =>
                setCreateForm((f) => ({ ...f, confirmPassword: passwordValue(e) }))
              }
              show={createShowPwd}
              onToggleShow={() => setCreateShowPwd((v) => !v)}
              disabled={saving}
              placeholder="Confirm password"
              showCopy={false}
            />
            <div className="col-12" style={{ fontSize: "0.8rem", color: "var(--pmf-text-muted)" }}>
              <i className="pi pi-info-circle mr-1" />
              The user will be required to change this password to their own private password upon first login.
            </div>
          </div>
        </Dialog>

        <Dialog
          header="Edit user"
          visible={editOpen}
          style={{ width: "min(36rem, 94vw)" }}
          className="rc-users-dialog"
          modal
          onHide={() => !saving && setEditOpen(false)}
          footer={
            <div className="rc-users__dialog-footer">
              <Button
                type="button"
                label="Cancel"
                outlined
                size="small"
                disabled={saving}
                onClick={() => setEditOpen(false)}
              />
              <Button
                type="button"
                label="Save"
                icon="pi pi-check"
                size="small"
                loading={saving}
                onClick={saveEdit}
              />
            </div>
          }
        >
          {dialogError ? (
            <Message severity="error" text={dialogError} className="w-full mb-2" />
          ) : null}
          <div className="rc-users__form rc-users__form--grid">
            <label>
              Emp ID
              <SafeInputText
                profile="empId"
                value={editForm.empId}
                onChange={(e) =>
                  setEditForm((f) => ({
                    ...f,
                    empId: e.target.value.replace(/\D/g, "").slice(0, 6),
                  }))
                }
                disabled={saving}
                autoComplete="off"
                inputMode="numeric"
                maxLength={6}
                placeholder="e.g. 112233"
              />
            </label>
            <label>
              Name
              <SafeInputText
                profile="personName"
                value={editForm.name}
                onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                disabled={saving}
              />
            </label>
            <label>
              Department
              {isAdmin ? (
                <Dropdown
                  value={editForm.dept || null}
                  options={deptOptions}
                  onChange={(e) => {
                    const next = e.value || "";
                    setEditForm((f) => ({ ...f, dept: next, reportsToId: null }));
                    loadHeads(next);
                  }}
                  placeholder="Select department"
                  disabled={saving || deptOptions.length === 0}
                  className="w-full"
                />
              ) : (
                <SafeInputText profile="text" value={editForm.dept || user?.dept || dept || ""} disabled />
              )}
            </label>
            <label>
              Role
              {isAdmin ? (
                <Dropdown
                  value={editForm.role}
                  options={ROLE_OPTIONS_ADMIN}
                  onChange={(e) =>
                    setEditForm((f) => ({
                      ...f,
                      role: e.value,
                      reportsToId: e.value === "engineer" ? f.reportsToId : null,
                    }))
                  }
                  disabled={saving}
                  className="w-full"
                />
              ) : (
                <SafeInputText profile="text" value={roleLabel(editForm.role)} disabled />
              )}
            </label>
            {editForm.role === "engineer" ? (
              <label>
                Reporting officer
                <Dropdown
                  value={editForm.reportsToId}
                  options={headOptions}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, reportsToId: e.value || null }))
                  }
                  placeholder={
                    headOptions.length ? "Select dept head" : "No dept heads in this dept"
                  }
                  disabled={saving || headOptions.length === 0}
                  className="w-full"
                />
              </label>
            ) : null}
          </div>
        </Dialog>

        <Dialog
          header={
            resetTarget
              ? `Reset password — ${resetTarget.empId || resetTarget.name}`
              : "Reset password"
          }
          visible={resetOpen}
          style={{ width: "min(30rem, 94vw)" }}
          className="rc-users-dialog"
          modal
          onHide={closeResetDialog}
          footer={
            <div className="rc-users__dialog-footer">
              {resetShareReady ? (
                <Button
                  type="button"
                  label="Done"
                  icon="pi pi-check"
                  size="small"
                  onClick={closeResetDialog}
                />
              ) : (
                <>
                  <Button
                    type="button"
                    label="Cancel"
                    outlined
                    size="small"
                    disabled={saving}
                    onClick={closeResetDialog}
                  />
                  <Button
                    type="button"
                    label="Reset password"
                    icon="pi pi-key"
                    size="small"
                    loading={saving}
                    onClick={saveReset}
                  />
                </>
              )}
            </div>
          }
        >
          {dialogError ? (
            <Message severity="error" text={dialogError} className="w-full mb-2" />
          ) : null}
          {resetShareReady ? (
            <div className="rc-users__share-panel">
              <Message
                severity="success"
                className="w-full mb-2"
                text="Temporary password is set. Copy it and send it to the employee — they must change it on next login."
              />
              <TempPasswordField
                label="Temporary password to share"
                value={resetPassword}
                show={resetShowPwd}
                onToggleShow={() => setResetShowPwd((v) => !v)}
                readOnly
                placeholder=""
              />
            </div>
          ) : (
            <>
              <p className="rc-users__hint">
                Set a temporary password and share it with the user. Use{" "}
                <strong>Show</strong> / <strong>Copy</strong> after auto-generate.
                The user must change this password on their next login.
              </p>
              <div className="rc-users__form">
                <TempPasswordField
                  label="New temporary password"
                  value={resetPassword}
                  onChange={(e) => setResetPassword(passwordValue(e))}
                  show={resetShowPwd}
                  onToggleShow={() => setResetShowPwd((v) => !v)}
                  disabled={saving}
                  placeholder="At least 12 chars (upper, lower, digit, special)"
                  headerExtra={
                    <Button
                      type="button"
                      label="Auto-generate"
                      icon="pi pi-sparkles"
                      size="small"
                      text
                      className="p-0 text-xs"
                      disabled={saving}
                      onClick={() => {
                        const generated = generateCompliantPassword();
                        setResetPassword(generated);
                        setResetConfirm(generated);
                        setResetShowPwd(true);
                        toast.info("Generated — password is visible; Copy to share");
                      }}
                    />
                  }
                />
                <TempPasswordField
                  label="Confirm password"
                  value={resetConfirm}
                  onChange={(e) => setResetConfirm(passwordValue(e))}
                  show={resetShowPwd}
                  onToggleShow={() => setResetShowPwd((v) => !v)}
                  disabled={saving}
                  placeholder="Confirm password"
                  showCopy={false}
                />
              </div>
            </>
          )}
        </Dialog>
      </div>
    </AppShell>
  );
}
