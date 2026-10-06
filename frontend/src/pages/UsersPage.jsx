import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Dialog } from "primereact/dialog";
import { Dropdown } from "primereact/dropdown";
import { InputText } from "primereact/inputtext";
import { Message } from "primereact/message";
import { Navigate } from "react-router-dom";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import TableComponent, { TableActions, TableStatusBadge } from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { toast } from "@/lib/toast";
import { fetchDepartments } from "@/services/authApi";
import {
  createManagedUser,
  fetchAdminUsers,
  fetchDeptUsers,
  resetManagedUserPassword,
  updateManagedUser,
} from "@/services/routeCardApi";
import "./route-card-generation-alt.scss";
import "./users.scss";

/** PrimeReact Password can miss React state updates inside Dialogs; use plain input. */
function passwordValue(e) {
  return e?.target?.value ?? e?.value ?? "";
}

const EMP_ID_DIGITS = /^\d{6}$/;

function isValidEmployeeId(value) {
  return EMP_ID_DIGITS.test(String(value || "").trim());
}

const ROLE_OPTIONS_ADMIN = [
  { label: "Engineer", value: "engineer" },
  { label: "Dept head", value: "dept_head" },
];

const ROLE_OPTIONS_ENGINEER_ONLY = [{ label: "Engineer", value: "engineer" }];

function roleTone(role) {
  if (role === "admin") return "danger";
  if (role === "dept_head") return "info";
  return "neutral";
}

function roleLabel(role) {
  if (role === "admin") return "Admin";
  if (role === "dept_head") return "Dept head";
  return "Engineer";
}

const emptyCreate = () => ({
  empId: "",
  name: "",
  dept: "",
  role: "engineer",
  password: "",
  confirmPassword: "",
});

const emptyEdit = () => ({
  empId: "",
  name: "",
  dept: "",
  role: "engineer",
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
  const [dialogError, setDialogError] = useState("");

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

  const openCreate = () => {
    setCreateForm({
      ...emptyCreate(),
      dept: isAdmin ? "" : user?.dept || "",
      role: "engineer",
    });
    setDialogError("");
    setCreateOpen(true);
  };

  const openEdit = (row) => {
    setEditTarget(row);
    setEditForm({
      empId: row.empId || "",
      name: row.name || "",
      dept: row.dept || "",
      role: row.role === "admin" ? "engineer" : row.role,
    });
    setDialogError("");
    setEditOpen(true);
  };

  const openReset = (row) => {
    setResetTarget(row);
    setResetPassword("");
    setResetConfirm("");
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
    if (createForm.password.length < 4) {
      setDialogError("Password must be at least 4 characters");
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
    setSaving(true);
    setDialogError("");
    setError("");
    try {
      await createManagedUser({
        empId,
        name,
        dept: isAdmin ? createForm.dept : undefined,
        role: isAdmin ? createForm.role : "engineer",
        password: createForm.password,
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
    setSaving(true);
    setDialogError("");
    setError("");
    try {
      const payload = { empId, name };
      if (isAdmin) {
        payload.dept = editForm.dept;
        payload.role = editForm.role;
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
    if (!resetTarget?.id) return;
    if (resetPassword.length < 4) {
      setDialogError("Password must be at least 4 characters");
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
      setResetOpen(false);
      setResetTarget(null);
      setResetPassword("");
      setResetConfirm("");
      toast.success(
        `Password reset for ${res.empId || resetTarget.empId}. They can sign in with the new password now.`
      );
    } catch (err) {
      setDialogError(err.message || "Could not reset password");
    } finally {
      setSaving(false);
    }
  };

  const pageDescription = useMemo(() => {
    if (isAdmin) {
      return "Add department heads or engineers, edit details, and reset passwords.";
    }
    if (isDeptHead) {
      return dept
        ? `Manage engineers in ${dept} — add users, edit details, and reset passwords.`
        : "Add engineers, edit details, and reset passwords for your department.";
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
                label={isAdmin ? "Add user" : "Add engineer"}
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
          header={isAdmin ? "Add user" : "Add engineer"}
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
              <InputText
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
              <InputText
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
                  onChange={(e) => setCreateForm((f) => ({ ...f, dept: e.value || "" }))}
                  placeholder="Select department"
                  disabled={saving || deptOptions.length === 0}
                  className="w-full"
                />
              </label>
            ) : (
              <label>
                Department
                <InputText value={user?.dept || dept || ""} disabled />
              </label>
            )}
            <label>
              Role
              <Dropdown
                value={createForm.role}
                options={isAdmin ? ROLE_OPTIONS_ADMIN : ROLE_OPTIONS_ENGINEER_ONLY}
                onChange={(e) => setCreateForm((f) => ({ ...f, role: e.value }))}
                disabled={saving || !isAdmin}
                className="w-full"
              />
            </label>
            <label>
              Password
              <InputText
                type="password"
                value={createForm.password}
                onChange={(e) =>
                  setCreateForm((f) => ({ ...f, password: passwordValue(e) }))
                }
                disabled={saving}
                autoComplete="new-password"
              />
            </label>
            <label>
              Confirm password
              <InputText
                type="password"
                value={createForm.confirmPassword}
                onChange={(e) =>
                  setCreateForm((f) => ({ ...f, confirmPassword: passwordValue(e) }))
                }
                disabled={saving}
                autoComplete="new-password"
              />
            </label>
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
              <InputText
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
              <InputText
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
                  onChange={(e) => setEditForm((f) => ({ ...f, dept: e.value || "" }))}
                  placeholder="Select department"
                  disabled={saving || deptOptions.length === 0}
                  className="w-full"
                />
              ) : (
                <InputText value={editForm.dept || user?.dept || dept || ""} disabled />
              )}
            </label>
            <label>
              Role
              {isAdmin ? (
                <Dropdown
                  value={editForm.role}
                  options={ROLE_OPTIONS_ADMIN}
                  onChange={(e) => setEditForm((f) => ({ ...f, role: e.value }))}
                  disabled={saving}
                  className="w-full"
                />
              ) : (
                <InputText value={roleLabel(editForm.role)} disabled />
              )}
            </label>
          </div>
        </Dialog>

        <Dialog
          header={
            resetTarget
              ? `Reset password — ${resetTarget.empId || resetTarget.name}`
              : "Reset password"
          }
          visible={resetOpen}
          style={{ width: "min(28rem, 94vw)" }}
          className="rc-users-dialog"
          modal
          onHide={() => !saving && setResetOpen(false)}
          footer={
            <div className="rc-users__dialog-footer">
              <Button
                type="button"
                label="Cancel"
                outlined
                size="small"
                disabled={saving}
                onClick={() => setResetOpen(false)}
              />
              <Button
                type="button"
                label="Reset password"
                icon="pi pi-key"
                size="small"
                loading={saving}
                onClick={saveReset}
              />
            </div>
          }
        >
          {dialogError ? (
            <Message severity="error" text={dialogError} className="w-full mb-2" />
          ) : null}
          <p className="rc-users__hint">
            Set a temporary password and share it with the user. They can sign in immediately with
            Emp ID <strong>{resetTarget?.empId}</strong> and this new password.
          </p>
          <div className="rc-users__form rc-users__form--grid">
            <label>
              New password
              <InputText
                type="password"
                value={resetPassword}
                onChange={(e) => setResetPassword(passwordValue(e))}
                disabled={saving}
                autoComplete="new-password"
              />
            </label>
            <label>
              Confirm password
              <InputText
                type="password"
                value={resetConfirm}
                onChange={(e) => setResetConfirm(passwordValue(e))}
                disabled={saving}
                autoComplete="new-password"
              />
            </label>
          </div>
        </Dialog>
      </div>
    </AppShell>
  );
}
