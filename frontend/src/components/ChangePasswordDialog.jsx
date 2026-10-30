import { useState } from "react";
import { Dialog } from "primereact/dialog";
import { Button } from "primereact/button";
import { Message } from "primereact/message";
import SafeInputText from "@/components/SafeInputText";
import { sanitizeInput } from "@/lib/inputSafe";
import { PASSWORD_RULES, getPasswordErrors } from "@/lib/passwordPolicy";
import { changePassword } from "@/services/authApi";
import { toast } from "@/lib/toast";

export default function ChangePasswordDialog({
  visible,
  onHide,
  forceMode = false,
  onSuccess,
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const pwdErrors = getPasswordErrors(newPassword);
  const isMatch = Boolean(newPassword && newPassword === confirmPassword);
  const hasMismatch = Boolean(confirmPassword && newPassword !== confirmPassword);
  const canSubmit = currentPassword.trim() && pwdErrors.length === 0 && isMatch && !saving;

  const handleSubmit = async (e) => {
    e?.preventDefault();
    setTouched(true);
    if (!canSubmit) return;

    setSaving(true);
    setError("");
    try {
      const res = await changePassword({
        currentPassword,
        newPassword,
      });
      toast.success(res.detail || "Password changed successfully!");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setTouched(false);
      onSuccess?.(res.user);
      onHide?.();
    } catch (err) {
      setError(err.message || "Failed to change password");
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    if (forceMode || saving) return;
    setError("");
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setTouched(false);
    onHide?.();
  };

  return (
    <Dialog
      header={
        forceMode ? (
          <div className="flex align-items-center gap-2">
            <i className="pi pi-shield text-primary" style={{ fontSize: "1.25rem" }} />
            <span>Set Your Private Password</span>
          </div>
        ) : (
          "Change Password"
        )
      }
      visible={visible}
      style={{ width: "min(32rem, 94vw)" }}
      modal
      closable={!forceMode && !saving}
      closeOnEscape={!forceMode && !saving}
      onHide={handleClose}
      footer={
        <div className="flex justify-content-end gap-2">
          {!forceMode && (
            <Button
              type="button"
              label="Cancel"
              size="small"
              text
              disabled={saving}
              onClick={handleClose}
            />
          )}
          <Button
            type="button"
            label={forceMode ? "Save & Continue" : "Update Password"}
            icon="pi pi-check"
            size="small"
            loading={saving}
            disabled={!canSubmit}
            onClick={handleSubmit}
          />
        </div>
      }
    >
      <form onSubmit={handleSubmit} className="flex flex-column gap-3">
        {forceMode && (
          <div
            style={{
              padding: "0.75rem 1rem",
              background: "var(--pmf-surface-highlight, rgba(59, 130, 246, 0.08))",
              borderRadius: "6px",
              borderLeft: "4px solid var(--primary-color, #3b82f6)",
              fontSize: "0.85rem",
              lineHeight: 1.45,
            }}
          >
            <strong>Action Required:</strong> A temporary password was set for your account. Please set a new private password before proceeding so that only you know your credentials.
          </div>
        )}

        {error && (
          <Message severity="error" text={error} className="w-full" />
        )}

        <div className="flex flex-column gap-1">
          <label htmlFor="cp-current" style={{ fontSize: "0.875rem", fontWeight: 600 }}>
            {forceMode ? "Temporary Password" : "Current Password"}
          </label>
          <SafeInputText profile="password"
            id="cp-current"
            type="password"
            value={currentPassword}
            onChange={(e) => {
              setCurrentPassword(sanitizeInput(e.target.value, "password").value);
              if (error) setError("");
            }}
            placeholder={forceMode ? "Enter the temporary password you logged in with" : "Enter current password"}
            disabled={saving}
            autoComplete="current-password"
            className="w-full"
          />
        </div>

        <div className="flex flex-column gap-1">
          <label htmlFor="cp-new" style={{ fontSize: "0.875rem", fontWeight: 600 }}>
            New Password
          </label>
          <SafeInputText profile="password"
            id="cp-new"
            type="password"
            value={newPassword}
            onChange={(e) => {
              setNewPassword(sanitizeInput(e.target.value, "password").value);
              setTouched(true);
              if (error) setError("");
            }}
            placeholder="Enter new strong password"
            disabled={saving}
            autoComplete="new-password"
            className="w-full"
          />
        </div>

        <div className="flex flex-column gap-1">
          <label htmlFor="cp-confirm" style={{ fontSize: "0.875rem", fontWeight: 600 }}>
            Confirm New Password
          </label>
          <SafeInputText profile="password"
            id="cp-confirm"
            type="password"
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(sanitizeInput(e.target.value, "password").value);
              if (error) setError("");
            }}
            placeholder="Confirm new password"
            disabled={saving}
            autoComplete="new-password"
            className={hasMismatch ? "p-invalid w-full" : "w-full"}
          />
          {hasMismatch && (
            <small style={{ color: "var(--red-500, #ef4444)", fontSize: "0.75rem" }}>
              Passwords do not match.
            </small>
          )}
        </div>

        {/* Live Requirement Checklist */}
        <div
          style={{
            padding: "0.6rem 0.8rem",
            background: "var(--surface-50, rgba(0,0,0,0.03))",
            borderRadius: "6px",
            border: "1px solid var(--pmf-border, #e5e7eb)",
            fontSize: "0.78rem",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>Password Requirements:</div>
          <ul style={{ margin: 0, paddingLeft: "1.2rem", display: "flex", flexDirection: "column", gap: "0.2rem" }}>
            {PASSWORD_RULES.map((rule) => {
              const passed = rule.test(newPassword);
              return (
                <li
                  key={rule.id}
                  style={{
                    color: passed ? "var(--green-600, #16a34a)" : "var(--pmf-text-muted, #6b7280)",
                    fontWeight: passed ? 500 : 400,
                  }}
                >
                  <i
                    className={passed ? "pi pi-check mr-1" : "pi pi-circle mr-1"}
                    style={{ fontSize: "0.7rem" }}
                  />
                  {rule.label}
                </li>
              );
            })}
            <li
              style={{
                color: "var(--pmf-text-muted, #6b7280)",
                fontStyle: "italic",
              }}
            >
              <i className="pi pi-history mr-1" style={{ fontSize: "0.7rem" }} />
              Cannot reuse current password or your last 5 passwords
            </li>
          </ul>
        </div>
      </form>
    </Dialog>
  );
}
