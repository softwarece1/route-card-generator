import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "primereact/button";
import { Dialog } from "primereact/dialog";
import { Dropdown } from "primereact/dropdown";
import { IconField } from "primereact/iconfield";
import { InputIcon } from "primereact/inputicon";
import { InputText } from "primereact/inputtext";
import SafeInputText from "@/components/SafeInputText";
import SafeInputTextarea from "@/components/SafeInputTextarea";
import { Message } from "primereact/message";
import { Navigate, useSearchParams } from "react-router-dom";
import AppShell from "@/components/AppShell";
import PageHeader from "@/components/PageHeader";
import TableComponent, { TableActions, TableStatusBadge } from "@/components/TableComponent";
import { getUser } from "@/lib/auth";
import { sanitizeInput } from "@/lib/inputSafe";
import { generateCompliantPassword, getPasswordErrors } from "@/lib/passwordPolicy";
import { toast } from "@/lib/toast";
import { fetchSbus } from "@/services/authApi";
import {
  approveSignup,
  createManagedUser,
  fetchAdminUsers,
  fetchDepartments,
  fetchDeptHeadsForDepartment,
  fetchSbuHeads,
  fetchDeptUsers,
  fetchSignupApprovals,
  rejectSignup,
  resetManagedUserPassword,
  updateManagedUser,
} from "@/services/routeCardApi";
import "./route-card-generation-alt.scss";
import "./users.scss";

const ROLE_FILTER_ALL = [
  { label: "All roles", value: "" },
  { label: "Admin", value: "admin" },
  { label: "SBU head", value: "sbu_head" },
  { label: "Dept head", value: "dept_head" },
  { label: "Engineer", value: "engineer" },
];

const ROLE_FILTER_SBU_HEAD = [
  { label: "All roles", value: "" },
  { label: "Dept head", value: "dept_head" },
  { label: "Engineer", value: "engineer" },
];

const ROLE_FILTER_DEPT_HEAD = [
  { label: "All roles", value: "" },
  { label: "Engineer", value: "engineer" },
];

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
  { label: "SBU head", value: "sbu_head" },
];

const ROLE_OPTIONS_SBU_HEAD = [
  { label: "Engineer", value: "engineer" },
  { label: "Dept head", value: "dept_head" },
];

const ROLE_OPTIONS_DEPT_HEAD = [{ label: "Engineer", value: "engineer" }];

function roleTone(role) {
  if (role === "admin") return "danger";
  if (role === "sbu_head") return "info";
  if (role === "dept_head") return "warn";
  return "neutral";
}

function roleLabel(role) {
  if (role === "admin") return "Admin";
  if (role === "sbu_head") return "SBU head";
  if (role === "dept_head") return "Dept head";
  if (role === "ied") return "IED (legacy)";
  return "Engineer";
}

const emptyCreate = () => ({
  empId: "",
  name: "",
  sbu: "",
  departmentId: null,
  role: "engineer",
  reportsToId: null,
  password: "",
  confirmPassword: "",
});

const emptyEdit = () => ({
  empId: "",
  name: "",
  sbu: "",
  departmentId: null,
  role: "engineer",
  reportsToId: null,
});

export default function UsersPage() {
  const user = getUser();
  const isAdmin = user?.role === "admin";
  const isSbuHead = user?.role === "sbu_head";
  const isDeptHead = user?.role === "dept_head";
  const canManageUsers = isAdmin || isSbuHead || isDeptHead;
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab = searchParams.get("tab") === "pending" ? "pending" : "users";

  const [activeTab, setActiveTab] = useState(initialTab);
  const [users, setUsers] = useState([]);
  const [pending, setPending] = useState([]);
  const [sbuScope, setSbuScope] = useState("");
  const [sbus, setSbus] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [filterSbu, setFilterSbu] = useState("");
  const [filterRole, setFilterRole] = useState("");

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
  const [deptOptions, setDeptOptions] = useState([]);

  const [decideOpen, setDecideOpen] = useState(false);
  const [decideMode, setDecideMode] = useState("approve");
  const [decideTarget, setDecideTarget] = useState(null);
  const [decideRemark, setDecideRemark] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = isAdmin ? await fetchAdminUsers() : await fetchDeptUsers();
      setUsers(res.users || []);
      setSbuScope(res.sbu || user?.sbu || "");
    } catch (err) {
      setUsers([]);
      setError(err.message || "Could not load users");
    } finally {
      setLoading(false);
    }
  }, [isAdmin, user?.sbu]);

  const loadPending = useCallback(async () => {
    setPendingLoading(true);
    try {
      const res = await fetchSignupApprovals();
      setPending(res.items || []);
    } catch (err) {
      setPending([]);
      setError(err.message || "Could not load pending signups");
    } finally {
      setPendingLoading(false);
    }
  }, []);

  useEffect(() => {
    if (canManageUsers) {
      load();
      if (isAdmin || isSbuHead) loadPending();
    }
  }, [canManageUsers, isAdmin, isSbuHead, load, loadPending]);

  useEffect(() => {
    if (searchParams.get("tab") === "pending") {
      setActiveTab("pending");
    }
  }, [searchParams]);

  const selectTab = (tab) => {
    setActiveTab(tab);
    if (tab === "pending") {
      setSearchParams({ tab: "pending" }, { replace: true });
      loadPending();
    } else {
      setSearchParams({}, { replace: true });
    }
  };

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    fetchSbus()
      .then((rows) => {
        if (!cancelled) setSbus(Array.isArray(rows) ? rows : []);
      })
      .catch(() => {
        if (!cancelled) setSbus([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  const sbuOptions = useMemo(
    () =>
      sbus.map((d) => ({
        label: d.label || d.name,
        value: d.name || d.value,
      })),
    [sbus]
  );

  const sbuFilterOptions = useMemo(
    () => [{ label: "All SBUs", value: "" }, ...sbuOptions],
    [sbuOptions]
  );

  const roleFilterOptions = isAdmin
    ? ROLE_FILTER_ALL
    : isSbuHead
      ? ROLE_FILTER_SBU_HEAD
      : ROLE_FILTER_DEPT_HEAD;

  const filteredUsers = useMemo(() => {
    const q = String(search || "").trim().toLowerCase();
    const wantSbu = String(filterSbu || "").trim().toLowerCase();
    const wantRole = String(filterRole || "").trim();
    return (users || []).filter((u) => {
      if (wantRole && u.role !== wantRole) return false;
      if (isAdmin && wantSbu) {
        if ((u.sbu || "").trim().toLowerCase() !== wantSbu) return false;
      }
      if (!q) return true;
      const blob = `${u.empId || ""} ${u.name || ""} ${u.sbu || ""} ${roleLabel(u.role)} ${
        u.reportsToName || ""
      }`.toLowerCase();
      return blob.includes(q);
    });
  }, [users, search, filterSbu, filterRole, isAdmin]);

  const canManageRow = (row) => {
    if (!row || row.role === "admin") return false;
    if (isAdmin) return true;
    if (isSbuHead) return row.role === "engineer" || row.role === "dept_head";
    if (isDeptHead) return row.role === "engineer" && row.reportsToId === user?.id;
    return false;
  };

  const loadDepts = useCallback(async (sbuName) => {
    const d = (sbuName || "").trim();
    if (!d) {
      setDeptOptions([]);
      return;
    }
    try {
      const items = await fetchDepartments({ sbu: d, activeOnly: true });
      setDeptOptions(
        (items || []).map((x) => ({
          label: `${x.name} (${x.code})`,
          value: x.id,
        }))
      );
    } catch {
      setDeptOptions([]);
    }
  }, []);

  useEffect(() => {
    if (isSbuHead || isDeptHead) {
      const sbu = user?.sbu || "";
      if (sbu) loadDepts(sbu);
    }
  }, [isSbuHead, isDeptHead, user?.sbu, loadDepts]);

  const loadHeads = useCallback(async ({ sbuName, departmentId, role }) => {
    const wantRole = (role || "engineer").trim();
    try {
      if (wantRole === "dept_head") {
        const d = (sbuName || "").trim();
        if (!d) {
          setHeadOptions([]);
          return;
        }
        const items = await fetchSbuHeads(d);
        setHeadOptions(
          (items || []).map((h) => ({
            label: h.label || `${h.name} (${h.empId})`,
            value: h.id,
          }))
        );
        return;
      }
      if (wantRole === "engineer") {
        if (!departmentId) {
          setHeadOptions([]);
          return;
        }
        const items = await fetchDeptHeadsForDepartment(departmentId);
        setHeadOptions(
          (items || []).map((h) => ({
            label: h.label || `${h.name} (${h.empId})`,
            value: h.id,
          }))
        );
        return;
      }
      setHeadOptions([]);
    } catch {
      setHeadOptions([]);
    }
  }, []);

  const openCreate = () => {
    const sbuVal = isAdmin ? "" : user?.sbu || "";
    const deptId = isDeptHead ? user?.departmentId || null : null;
    setCreateForm({
      ...emptyCreate(),
      sbu: sbuVal,
      departmentId: deptId,
      role: "engineer",
      reportsToId: isDeptHead ? user?.id || null : null,
    });
    setCreateShowPwd(false);
    setDialogError("");
    setCreateOpen(true);
    if (sbuVal) loadDepts(sbuVal);
    else setDeptOptions([]);
    if (deptId || (sbuVal && false)) {
      loadHeads({ sbuName: sbuVal, departmentId: deptId, role: "engineer" });
    } else setHeadOptions([]);
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
    const role = row.role === "admin" ? "engineer" : row.role;
    setEditTarget(row);
    setEditForm({
      empId: row.empId || "",
      name: row.name || "",
      sbu: row.sbu || "",
      departmentId: row.departmentId || null,
      role,
      reportsToId: row.reportsToId || null,
    });
    setDialogError("");
    setEditOpen(true);
    if (row.sbu) loadDepts(row.sbu);
    else setDeptOptions([]);
    loadHeads({
      sbuName: row.sbu,
      departmentId: row.departmentId,
      role,
    });
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
    if ((isAdmin || isSbuHead) && !createForm.sbu && isAdmin) {
      setDialogError("Select an SBU");
      return;
    }
    const role = isAdmin
      ? createForm.role
      : isSbuHead
        ? createForm.role
        : "engineer";
    if (role !== "sbu_head" && !createForm.departmentId) {
      setDialogError("Select a department");
      return;
    }
    if ((role === "engineer" || role === "dept_head") && !createForm.reportsToId) {
      setDialogError(
        role === "engineer"
          ? "Select a reporting officer (department head)"
          : "Select a reporting officer (SBU head)"
      );
      return;
    }
    setSaving(true);
    setDialogError("");
    setError("");
    try {
      await createManagedUser({
        empId,
        name,
        sbu: isAdmin ? createForm.sbu : undefined,
        departmentId: role === "sbu_head" ? undefined : createForm.departmentId,
        role,
        password: createForm.password,
        reportsToId:
          role === "engineer" || role === "dept_head"
            ? createForm.reportsToId
            : undefined,
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
    if (isAdmin && !editForm.sbu) {
      setDialogError("Select an SBU");
      return;
    }
    const role = isAdmin || isSbuHead ? editForm.role : editTarget.role;
    if (role !== "sbu_head" && !editForm.departmentId) {
      setDialogError("Select a department");
      return;
    }
    if ((role === "engineer" || role === "dept_head") && !editForm.reportsToId) {
      setDialogError("Select a reporting officer");
      return;
    }
    setSaving(true);
    setDialogError("");
    setError("");
    try {
      const payload = { empId, name };
      if (isAdmin) {
        payload.sbu = editForm.sbu;
        payload.role = editForm.role;
        payload.departmentId =
          editForm.role === "sbu_head" ? null : editForm.departmentId;
      } else if (isSbuHead) {
        payload.role = editForm.role;
        payload.departmentId = editForm.departmentId;
      }
      if (role === "engineer" || role === "dept_head") {
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
                sbu: updated.sbu,
                role: updated.role,
                departmentId: updated.departmentId,
                departmentName: updated.departmentName,
                departmentCode: updated.departmentCode,
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
      return "Add SBU heads, dept heads, and engineers; assign departments; approve signups.";
    }
    if (isSbuHead) {
      return sbuScope
        ? `Manage dept heads and engineers in ${sbuScope}; approve pending signups.`
        : "Manage dept heads and engineers; approve pending signups.";
    }
    if (isDeptHead) {
      return "Manage engineers who report to you.";
    }
    return "";
  }, [isAdmin, isSbuHead, isDeptHead, sbuScope]);

  const openDecide = (row, mode) => {
    setDecideTarget(row);
    setDecideMode(mode);
    setDecideRemark("");
    setDialogError("");
    setDecideOpen(true);
  };

  const submitDecide = async () => {
    if (!decideTarget) return;
    if (decideMode === "reject" && !String(decideRemark || "").trim()) {
      setDialogError("Remark is required to reject");
      return;
    }
    setSaving(true);
    setDialogError("");
    try {
      if (decideMode === "approve") {
        await approveSignup(decideTarget.id, decideRemark.trim());
        toast.success(`Approved ${decideTarget.empId}`);
      } else {
        await rejectSignup(decideTarget.id, decideRemark.trim());
        toast.success(`Rejected ${decideTarget.empId}`);
      }
      setDecideOpen(false);
      setDecideTarget(null);
      await loadPending();
      await load();
    } catch (err) {
      setDialogError(err.message || "Could not update signup");
    } finally {
      setSaving(false);
    }
  };

  if (!canManageUsers) {
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
                onClick={() => {
                  load();
                  loadPending();
                }}
              />
              {activeTab === "users" ? (
                <Button
                  type="button"
                  label="Add user"
                  icon="pi pi-user-plus"
                  size="small"
                  onClick={openCreate}
                />
              ) : null}
            </>
          }
        />
        {error ? <Message severity="error" text={error} className="w-full mb-3" /> : null}

        <div className="rc-users__tabs-row">
          <div className="rc-users__tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "users"}
              className={`rc-users__tab${activeTab === "users" ? " rc-users__tab--active" : ""}`}
              onClick={() => selectTab("users")}
            >
              <i className="pi pi-users" aria-hidden />
              Directory
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "pending"}
              className={`rc-users__tab${activeTab === "pending" ? " rc-users__tab--active" : ""}`}
              onClick={() => selectTab("pending")}
            >
              <i className="pi pi-clock" aria-hidden />
              Pending signups
              {pending.length > 0 ? (
                <span className="rc-users__tab-badge">{pending.length}</span>
              ) : null}
            </button>
          </div>
          {activeTab === "users" ? (
            <div className="rc-users__tabs-tools">
              <IconField iconPosition="left" className="rc-users__search">
                <InputIcon className="pi pi-search" />
                <InputText
                  placeholder="Search name, emp ID…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </IconField>
              {isAdmin ? (
                <Dropdown
                  value={filterSbu || null}
                  options={sbuFilterOptions}
                  optionLabel="label"
                  optionValue="value"
                  onChange={(e) =>
                    setFilterSbu(e.value == null || e.value === "" ? "" : String(e.value))
                  }
                  placeholder="SBU"
                  showClear
                  className="rc-users__filter"
                />
              ) : null}
              <Dropdown
                value={filterRole || null}
                options={roleFilterOptions}
                optionLabel="label"
                optionValue="value"
                onChange={(e) =>
                  setFilterRole(e.value == null || e.value === "" ? "" : String(e.value))
                }
                placeholder="Role"
                showClear
                className="rc-users__filter rc-users__filter--role"
              />
            </div>
          ) : null}
        </div>

        {activeTab === "users" ? (
          <>
        <TableComponent
          value={filteredUsers}
          loading={loading}
          dataKey="id"
          paginator
          rows={10}
          emptyMessage={
            search.trim() || filterSbu || filterRole
              ? "No users match your search / filters."
              : "No users found."
          }
          columns={[
            { type: "index", header: "#", style: { width: "3.25rem" } },
            { field: "empId", header: "Emp ID", sortable: true, style: { width: "8.5rem" } },
            { field: "name", header: "Name", sortable: true },
            ...(isAdmin
              ? [{ field: "sbu", header: "SBU", sortable: true, style: { width: "9rem" } }]
              : []),
            {
              header: "Department",
              style: { width: "8rem" },
              body: (row) => row.departmentName || row.departmentCode || "—",
            },
            {
              header: "Role",
              style: { width: "8rem" },
              body: (row) => (
                <TableStatusBadge value={roleLabel(row.role)} tone={roleTone(row.role)} />
              ),
            },
            {
              header: "Status",
              style: { width: "7.5rem" },
              body: (row) => {
                const st = row.approvalStatus || (row.isActive ? "approved" : "inactive");
                if (st === "pending") {
                  return <TableStatusBadge value="Pending" tone="warn" />;
                }
                if (st === "rejected") {
                  return <TableStatusBadge value="Rejected" tone="danger" />;
                }
                return (
                  <TableStatusBadge
                    value={row.isActive ? "Active" : "Inactive"}
                    tone={row.isActive ? "success" : "neutral"}
                  />
                );
              },
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
          </>
        ) : (
          <TableComponent
            value={pending}
            loading={pendingLoading}
            dataKey="id"
            paginator
            rows={10}
            emptyMessage="No pending engineer signups."
            columns={[
              { type: "index", header: "#", style: { width: "3.25rem" } },
              { field: "empId", header: "Emp ID", sortable: true, style: { width: "8.5rem" } },
              { field: "name", header: "Name", sortable: true },
              { field: "sbu", header: "SBU", sortable: true, style: { width: "9rem" } },
              {
                header: "Requested",
                style: { width: "11rem" },
                body: (row) => {
                  const raw = row.requestedAt || row.createdAt;
                  if (!raw) return "—";
                  try {
                    return new Date(raw).toLocaleString();
                  } catch {
                    return raw;
                  }
                },
              },
              {
                header: "Actions",
                style: { width: "10rem" },
                body: (row) => (
                  <TableActions>
                    <Button
                      type="button"
                      label="Approve"
                      icon="pi pi-check"
                      size="small"
                      onClick={() => openDecide(row, "approve")}
                    />
                    <Button
                      type="button"
                      label="Reject"
                      icon="pi pi-times"
                      size="small"
                      outlined
                      severity="danger"
                      onClick={() => openDecide(row, "reject")}
                    />
                  </TableActions>
                ),
              },
            ]}
          />
        )}

        <Dialog
          header={
            decideMode === "approve"
              ? `Approve ${decideTarget?.empId || "signup"}`
              : `Reject ${decideTarget?.empId || "signup"}`
          }
          visible={decideOpen}
          style={{ width: "min(28rem, 94vw)" }}
          className="rc-users-dialog p-confirm-dialog-sm"
          modal
          onHide={() => !saving && setDecideOpen(false)}
          footer={
            <div className="rc-users__dialog-footer">
              <Button
                type="button"
                label="Cancel"
                outlined
                size="small"
                disabled={saving}
                onClick={() => setDecideOpen(false)}
              />
              <Button
                type="button"
                label={decideMode === "approve" ? "Approve" : "Reject"}
                size="small"
                severity={decideMode === "reject" ? "danger" : undefined}
                loading={saving}
                disabled={saving}
                onClick={submitDecide}
              />
            </div>
          }
        >
          <div className="rc-users__form">
            {decideTarget ? (
              <p style={{ margin: 0, fontSize: "0.85rem" }}>
                {decideTarget.name} ({decideTarget.empId})
                {decideTarget.sbu ? ` · ${decideTarget.sbu}` : ""}
              </p>
            ) : null}
            <label>
              Remark{decideMode === "reject" ? " (required)" : " (optional)"}
              <SafeInputTextarea
                profile="multiline"
                value={decideRemark}
                onChange={(e) => setDecideRemark(e.target.value)}
                rows={3}
                autoResize
                disabled={saving}
                placeholder={
                  decideMode === "reject"
                    ? "Reason for rejection"
                    : "Optional note for the employee"
                }
              />
            </label>
            {dialogError ? <Message severity="error" text={dialogError} className="w-full" /> : null}
          </div>
        </Dialog>

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
                SBU
                <Dropdown
                  value={createForm.sbu || null}
                  options={sbuOptions}
                  onChange={(e) => {
                    const next = e.value || "";
                    setCreateForm((f) => ({
                      ...f,
                      sbu: next,
                      departmentId: null,
                      reportsToId: null,
                    }));
                    loadDepts(next);
                    setHeadOptions([]);
                  }}
                  placeholder="Select SBU"
                  disabled={saving || sbuOptions.length === 0}
                  className="w-full"
                />
              </label>
            ) : (
              <label>
                SBU
                <SafeInputText profile="text" value={user?.sbu || sbuScope || ""} disabled />
              </label>
            )}
            {createForm.role !== "sbu_head" ? (
              <label>
                Department
                <Dropdown
                  value={createForm.departmentId}
                  options={deptOptions}
                  onChange={(e) => {
                    const deptId = e.value || null;
                    setCreateForm((f) => ({
                      ...f,
                      departmentId: deptId,
                      reportsToId:
                        f.role === "engineer" && isDeptHead ? user?.id || null : null,
                    }));
                    loadHeads({
                      sbuName: createForm.sbu || user?.sbu,
                      departmentId: deptId,
                      role: createForm.role,
                    });
                  }}
                  placeholder={
                    deptOptions.length ? "Select department" : "No departments in this SBU"
                  }
                  disabled={saving || isDeptHead || deptOptions.length === 0}
                  className="w-full"
                />
              </label>
            ) : null}
            <label>
              Role
              <Dropdown
                value={createForm.role}
                options={
                  isAdmin
                    ? ROLE_OPTIONS_ADMIN
                    : isSbuHead
                      ? ROLE_OPTIONS_SBU_HEAD
                      : ROLE_OPTIONS_DEPT_HEAD
                }
                onChange={(e) => {
                  const nextRole = e.value;
                  setCreateForm((f) => ({
                    ...f,
                    role: nextRole,
                    departmentId: nextRole === "sbu_head" ? null : f.departmentId,
                    reportsToId:
                      nextRole === "engineer" && isDeptHead
                        ? user?.id || null
                        : nextRole === "dept_head" && isSbuHead
                          ? user?.id || null
                          : null,
                  }));
                  loadHeads({
                    sbuName: createForm.sbu || user?.sbu,
                    departmentId: createForm.departmentId,
                    role: nextRole,
                  });
                }}
                disabled={saving || isDeptHead}
                className="w-full"
              />
            </label>
            {createForm.role === "engineer" || createForm.role === "dept_head" ? (
              <label>
                Reporting officer
                <Dropdown
                  value={createForm.reportsToId}
                  options={headOptions}
                  onChange={(e) =>
                    setCreateForm((f) => ({ ...f, reportsToId: e.value || null }))
                  }
                  placeholder={
                    createForm.role === "engineer"
                      ? headOptions.length
                        ? "Select department head"
                        : "No department heads in this department"
                      : headOptions.length
                        ? "Select SBU head"
                        : "No SBU heads in this SBU"
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
              SBU
              {isAdmin ? (
                <Dropdown
                  value={editForm.sbu || null}
                  options={sbuOptions}
                  onChange={(e) => {
                    const next = e.value || "";
                    setEditForm((f) => ({
                      ...f,
                      sbu: next,
                      departmentId: null,
                      reportsToId: null,
                    }));
                    loadDepts(next);
                    setHeadOptions([]);
                  }}
                  placeholder="Select SBU"
                  disabled={saving || sbuOptions.length === 0}
                  className="w-full"
                />
              ) : (
                <SafeInputText profile="text" value={editForm.sbu || user?.sbu || sbuScope || ""} disabled />
              )}
            </label>
            {editForm.role !== "sbu_head" ? (
              <label>
                Department
                <Dropdown
                  value={editForm.departmentId}
                  options={deptOptions}
                  onChange={(e) => {
                    const deptId = e.value || null;
                    setEditForm((f) => ({
                      ...f,
                      departmentId: deptId,
                      reportsToId: null,
                    }));
                    loadHeads({
                      sbuName: editForm.sbu || user?.sbu,
                      departmentId: deptId,
                      role: editForm.role,
                    });
                  }}
                  placeholder={
                    deptOptions.length ? "Select department" : "No departments in this SBU"
                  }
                  disabled={saving || isDeptHead || deptOptions.length === 0}
                  className="w-full"
                />
              </label>
            ) : null}
            <label>
              Role
              {isAdmin || isSbuHead ? (
                <Dropdown
                  value={editForm.role}
                  options={isAdmin ? ROLE_OPTIONS_ADMIN : ROLE_OPTIONS_SBU_HEAD}
                  onChange={(e) => {
                    const nextRole = e.value;
                    setEditForm((f) => ({
                      ...f,
                      role: nextRole,
                      departmentId: nextRole === "sbu_head" ? null : f.departmentId,
                      reportsToId: null,
                    }));
                    loadHeads({
                      sbuName: editForm.sbu || user?.sbu,
                      departmentId: editForm.departmentId,
                      role: nextRole,
                    });
                  }}
                  disabled={saving}
                  className="w-full"
                />
              ) : (
                <SafeInputText profile="text" value={roleLabel(editForm.role)} disabled />
              )}
            </label>
            {editForm.role === "engineer" || editForm.role === "dept_head" ? (
              <label>
                Reporting officer
                <Dropdown
                  value={editForm.reportsToId}
                  options={headOptions}
                  onChange={(e) =>
                    setEditForm((f) => ({ ...f, reportsToId: e.value || null }))
                  }
                  placeholder={
                    editForm.role === "engineer"
                      ? headOptions.length
                        ? "Select department head"
                        : "No department heads in this department"
                      : headOptions.length
                        ? "Select SBU head"
                        : "No SBU heads in this SBU"
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
