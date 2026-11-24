import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Button } from "primereact/button";
import { Password } from "primereact/password";
import { Dropdown } from "primereact/dropdown";
import {
  signup,
  fetchSbus,
  fetchEmpStatus,
} from "@/services/authApi";
import { isAuthenticated } from "@/lib/auth";
import { sanitizeInput } from "@/lib/inputSafe";
import { getPasswordErrors } from "@/lib/passwordPolicy";
import AuthLogo from "@/components/AuthLogo";
import SafeInputText from "@/components/SafeInputText";
import ThemeToggle from "@/components/ThemeToggle";
import heroImg from "@/assets/hero.png";
import "./login.scss";

const EMP_ID_DIGITS = /^\d{6}$/;

function isValidEmployeeId(value) {
  return EMP_ID_DIGITS.test(String(value || "").trim());
}

function employeeSbu(employee) {
  if (!employee) return null;
  return employee.sbu || employee.dept || null;
}

export default function SignupPage() {
  const navigate = useNavigate();
  const empCheckSeq = useRef(0);

  if (isAuthenticated()) {
    return <Navigate to="/generator" replace />;
  }

  const [empId, setEmpId] = useState("");
  const [name, setName] = useState("");
  const [sbu, setSbu] = useState(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [passwordTouched, setPasswordTouched] = useState(false);
  const [passwordServerError, setPasswordServerError] = useState("");
  const [formError, setFormError] = useState("");
  const [pendingSuccess, setPendingSuccess] = useState(null);

  const [sbus, setSbus] = useState([]);
  const [sbusLoading, setSbusLoading] = useState(true);

  const [empStatus, setEmpStatus] = useState(null);
  const [verifiedEmployee, setVerifiedEmployee] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setSbusLoading(true);
      try {
        const rows = await fetchSbus();
        if (!cancelled) setSbus(rows);
      } catch {
        if (!cancelled) setSbus([]);
      } finally {
        if (!cancelled) setSbusLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const checkEmpId = useCallback(async (raw) => {
    const id = (raw || "").trim();
    if (!id) {
      setEmpStatus(null);
      setVerifiedEmployee(null);
      return;
    }
    const seq = ++empCheckSeq.current;
    try {
      const status = await fetchEmpStatus(id);
      if (seq !== empCheckSeq.current) return;
      setEmpStatus(status);
      if (status?.verified && status.employee) {
        setVerifiedEmployee(status.employee);
        if (status.employee.name) setName(status.employee.name);
        const lockedSbu = employeeSbu(status.employee);
        if (lockedSbu) setSbu(lockedSbu);
      } else {
        setVerifiedEmployee(null);
      }
    } catch {
      if (seq !== empCheckSeq.current) return;
      setEmpStatus(null);
      setVerifiedEmployee(null);
    }
  }, []);

  const passwordErrors = getPasswordErrors(password);
  const passwordOk = password.length > 0 && passwordErrors.length === 0 && !passwordServerError;
  const passwordsMatch = password.length > 0 && password === confirmPassword;
  const confirmMismatch = Boolean(confirmPassword) && password !== confirmPassword;
  const nameLocked = Boolean(verifiedEmployee?.name);
  const sbuLocked = Boolean(employeeSbu(verifiedEmployee));

  const empInvalid =
    submitted &&
    (!empId.trim() || !isValidEmployeeId(empId) || Boolean(empStatus?.registered));
  const nameInvalid = submitted && !name.trim() && !nameLocked;
  const sbuInvalid = submitted && !sbu && !sbuLocked;
  const passwordInvalid = (submitted || passwordTouched) && !passwordOk;
  const confirmInvalid = (submitted && !confirmPassword) || confirmMismatch;

  const canSubmit =
    isValidEmployeeId(empId) &&
    name.trim() &&
    sbu &&
    passwordOk &&
    passwordsMatch &&
    !confirmMismatch &&
    !empStatus?.registered &&
    !sbusLoading &&
    sbus.length > 0;

  const onSubmit = async (e) => {
    e.preventDefault();
    setSubmitted(true);
    setPasswordTouched(true);
    setFormError("");
    setPasswordServerError("");
    if (!canSubmit) return;

    setLoading(true);
    try {
      const data = await signup({
        empId: empId.trim(),
        name: name.trim(),
        sbu,
        password,
      });
      setPendingSuccess({
        message:
          data?.message ||
          "Signup submitted. Awaiting SBU head approval. You can sign in after it is approved.",
        empId: data?.user?.empId || empId.trim(),
        sbu: data?.user?.sbu || sbu,
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === "string" ? detail : err?.message || "Could not create account";
      const lower = msg.toLowerCase();
      if (
        lower.includes("password") ||
        lower.includes("compromised") ||
        lower.includes("too common") ||
        lower.includes("complexity")
      ) {
        setPasswordServerError(msg);
      } else {
        setFormError(msg);
      }
    } finally {
      setLoading(false);
    }
  };


  return (
    <div className="rc-login">
      <div className="rc-login__theme">
        <ThemeToggle />
      </div>
      <div className="rc-login__panel">
        <aside className="rc-login__hero" aria-hidden="true">
          <img src={heroImg} alt="" className="rc-login__hero-img" />
        </aside>

        <div className="rc-login__card">
          {pendingSuccess ? (
            <div className="rc-login__form">
              <div className="rc-login__brand">
                <AuthLogo size={36} />
                <h1>Awaiting approval</h1>
                <p>Your signup was sent to the SBU head</p>
              </div>
              <div className="rc-login__form-error" style={{ color: "inherit", background: "transparent" }}>
                {pendingSuccess.message}
              </div>
              <p className="rc-login__hint" style={{ marginTop: "0.75rem" }}>
                Employee ID <strong>{pendingSuccess.empId}</strong>
                {pendingSuccess.sbu ? (
                  <>
                    {" "}
                    · SBU <strong>{pendingSuccess.sbu}</strong>
                  </>
                ) : null}
              </p>
              <Button
                type="button"
                label="Go to sign in"
                className="rc-login__cta"
                size="small"
                onClick={() => navigate("/login", { replace: true })}
              />
              <p className="rc-login__hint">
                <Link to="/about">About the app</Link>
              </p>
            </div>
          ) : (
          <form className="rc-login__form" onSubmit={onSubmit} noValidate>
            <div className="rc-login__brand">
              <AuthLogo size={36} />
              <h1>Create account</h1>
              <p>Choose your SBU — signup is sent for SBU head approval</p>
            </div>

            {formError ? <div className="rc-login__form-error">{formError}</div> : null}

            <div className="rc-login__field">
              <label className="rc-login__label" htmlFor="empId">
                Employee ID
              </label>
              <SafeInputText
                id="empId"
                profile="empId"
                value={empId}
                onChange={(e) => {
                  const next = String(e.target.value || "").replace(/\D/g, "").slice(0, 6);
                  setEmpId(next);
                  setEmpStatus(null);
                  setVerifiedEmployee(null);
                  if (formError) setFormError("");
                }}
                onBlur={() => checkEmpId(empId)}
                placeholder="6-digit employee ID"
                inputMode="numeric"
                maxLength={6}
                autoComplete="username"
                disabled={loading}
                className={empInvalid ? "p-invalid" : undefined}
                aria-invalid={empInvalid}
              />
              {submitted && empId.trim() && !isValidEmployeeId(empId) ? (
                <small className="rc-login__hint" style={{ color: "var(--pmf-danger, #b91c1c)" }}>
                  Employee ID must be exactly 6 digits
                </small>
              ) : (
                <small className="rc-login__hint">Use your 6-digit employee ID</small>
              )}
            </div>

            {verifiedEmployee ? (
              <div className="rc-login__verified" aria-live="polite">
                {verifiedEmployee.name ? (
                  <div className="rc-login__verified-row">
                    <span className="rc-login__verified-label">Name</span>
                    <span className="rc-login__verified-value">{verifiedEmployee.name}</span>
                  </div>
                ) : null}
                {employeeSbu(verifiedEmployee) ? (
                  <div className="rc-login__verified-row">
                    <span className="rc-login__verified-label">SBU</span>
                    <span className="rc-login__verified-value">{employeeSbu(verifiedEmployee)}</span>
                  </div>
                ) : null}
              </div>
            ) : null}

            {!nameLocked ? (
              <div className="rc-login__field">
                <label className="rc-login__label" htmlFor="name">
                  Name
                </label>
                <SafeInputText
                  id="name"
                  profile="personName"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Enter full name"
                  autoComplete="name"
                  disabled={loading}
                  className={nameInvalid ? "p-invalid" : undefined}
                  aria-invalid={nameInvalid}
                  maxLength={255}
                />
              </div>
            ) : null}

            {!sbuLocked ? (
              <div className="rc-login__field">
                <label className="rc-login__label" htmlFor="sbu">
                  SBU
                </label>
                <Dropdown
                  id="sbu"
                  value={sbu}
                  options={sbus}
                  optionLabel="label"
                  optionValue="value"
                  onChange={(e) => setSbu(e.value)}
                  placeholder={sbusLoading ? "Loading…" : "Select SBU"}
                  disabled={loading || sbusLoading || sbus.length === 0}
                  className={sbuInvalid ? "p-invalid w-full" : "w-full"}
                  emptyMessage="No SBUs available"
                />
              </div>
            ) : null}

            <div className="rc-login__field">
              <label className="rc-login__label" htmlFor="password">
                Password
              </label>
              <Password
                id="password"
                value={password}
                onChange={(e) => {
                  setPassword(sanitizeInput(e.target.value, "password").value);
                  setPasswordTouched(true);
                  setPasswordServerError("");
                  if (formError) setFormError("");
                }}
                onBlur={() => {
                  if (password) setPasswordTouched(true);
                }}
                placeholder="Enter password"
                feedback={false}
                toggleMask
                autoComplete="new-password"
                disabled={loading}
                className={passwordInvalid ? "p-invalid w-full" : "w-full"}
                inputClassName="w-full"
                aria-invalid={passwordInvalid}
              />
              {passwordInvalid && (
                <div
                  className="rc-login__field-error"
                  style={{
                    color: "var(--pmf-danger, #b91c1c)",
                    fontSize: "0.78rem",
                    marginTop: "0.35rem",
                    lineHeight: 1.35,
                  }}
                >
                  <span style={{ fontWeight: 600 }}>Password must:</span>
                  <ul style={{ margin: "0.2rem 0 0", paddingLeft: "1.2rem", listStyleType: "disc" }}>
                    {passwordErrors.map((err) => (
                      <li key={err}>{err}</li>
                    ))}
                  </ul>
                  {passwordServerError ? (
                    <div style={{ marginTop: "0.25rem", fontWeight: 600 }}>{passwordServerError}</div>
                  ) : null}
                </div>
              )}
            </div>

            <div className="rc-login__field">
              <label className="rc-login__label" htmlFor="confirmPassword">
                Confirm Password
              </label>
              <Password
                id="confirmPassword"
                value={confirmPassword}
                onChange={(e) => {
                  setConfirmPassword(sanitizeInput(e.target.value, "password").value);
                  if (formError) setFormError("");
                }}
                placeholder="Confirm password"
                feedback={false}
                toggleMask
                autoComplete="new-password"
                disabled={loading}
                className={confirmInvalid ? "p-invalid w-full" : "w-full"}
                inputClassName="w-full"
                aria-invalid={confirmInvalid}
              />
              {confirmMismatch ? (
                <small
                  className="rc-login__hint"
                  style={{
                    color: "var(--pmf-danger, #b91c1c)",
                    display: "block",
                    marginTop: "0.25rem",
                    textAlign: "left",
                  }}
                >
                  Passwords do not match.
                </small>
              ) : submitted && !confirmPassword ? (
                <small
                  className="rc-login__hint"
                  style={{
                    color: "var(--pmf-danger, #b91c1c)",
                    display: "block",
                    marginTop: "0.25rem",
                    textAlign: "left",
                  }}
                >
                  Please confirm your password.
                </small>
              ) : null}
            </div>

            <Button
              type="submit"
              label={loading ? "Sending..." : "Send for approval"}
              className="rc-login__cta"
              size="small"
              loading={loading}
              disabled={loading}
            />

            <p className="rc-login__hint">
              Already registered? <Link to="/login">Sign in</Link>
              <br />
              <Link to="/about">About the app</Link>
            </p>
          </form>
          )}
        </div>
      </div>
    </div>
  );
}