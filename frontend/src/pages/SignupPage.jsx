import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Button } from "primereact/button";
import { Password } from "primereact/password";
import { Dropdown } from "primereact/dropdown";
import {
  signup,
  fetchDepartments,
  fetchEmpStatus,
} from "@/services/authApi";
import { isAuthenticated } from "@/lib/auth";
import { sanitizeInput } from "@/lib/inputSafe";
import AuthLogo from "@/components/AuthLogo";
import SafeInputText from "@/components/SafeInputText";
import ThemeToggle from "@/components/ThemeToggle";
import heroImg from "@/assets/hero.png";
import "./login.scss";

const EMP_ID_DIGITS = /^\d{6}$/;

const PASSWORD_RULES = [
  { id: "length", label: "Contain at least 12 characters", test: (p) => p.length >= 12 },
  { id: "maxLength", label: "Not exceed 64 characters", test: (p) => p.length <= 64 },
  { id: "noSpaces", label: "Not contain spaces", test: (p) => !/\s/.test(p) },
  { id: "uppercase", label: "Contain at least one uppercase letter", test: (p) => /[A-Z]/.test(p) },
  { id: "lowercase", label: "Contain at least one lowercase letter", test: (p) => /[a-z]/.test(p) },
  { id: "digit", label: "Contain at least one number", test: (p) => /\d/.test(p) },
  {
    id: "special",
    label: "Contain at least one special character",
    test: (p) => /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>/?]/.test(p),
  },
];

const COMMON_PASSWORDS = new Set([
  "password", "password123", "admin123456", "123456789012",
  "welcome12345", "qwerty123456", "routecard123", "administrator",
]);

function getPasswordErrors(pwd) {
  if (!pwd) return ["Contain at least 12 characters", "Contain at least one uppercase letter", "Contain at least one lowercase letter", "Contain at least one number", "Contain at least one special character", "Not contain spaces"];
  const failed = [];
  for (const rule of PASSWORD_RULES) {
    if (!rule.test(pwd)) {
      failed.push(rule.label);
    }
  }
  if (COMMON_PASSWORDS.has(pwd.toLowerCase())) {
    failed.push("Not be a commonly used or compromised password");
  }
  return failed;
}

function isValidEmployeeId(value) {
  return EMP_ID_DIGITS.test(String(value || "").trim());
}

export default function SignupPage() {
  const navigate = useNavigate();
  const empCheckSeq = useRef(0);

  if (isAuthenticated()) {
    return <Navigate to="/generator" replace />;
  }

  const [empId, setEmpId] = useState("");
  const [name, setName] = useState("");
  const [dept, setDept] = useState(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [passwordTouched, setPasswordTouched] = useState(false);
  const [passwordServerError, setPasswordServerError] = useState("");
  const [formError, setFormError] = useState("");

  const [departments, setDepartments] = useState([]);
  const [deptsLoading, setDeptsLoading] = useState(true);

  const [empStatus, setEmpStatus] = useState(null);
  const [verifiedEmployee, setVerifiedEmployee] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setDeptsLoading(true);
      try {
        const rows = await fetchDepartments();
        if (!cancelled) setDepartments(rows);
      } catch {
        if (!cancelled) setDepartments([]);
      } finally {
        if (!cancelled) setDeptsLoading(false);
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
        if (status.employee.dept) setDept(status.employee.dept);
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
  const deptLocked = Boolean(verifiedEmployee?.dept);

  const empInvalid =
    submitted &&
    (!empId.trim() || !isValidEmployeeId(empId) || Boolean(empStatus?.registered));
  const nameInvalid = submitted && !name.trim() && !nameLocked;
  const deptInvalid = submitted && !dept && !deptLocked;
  const passwordInvalid = (submitted || passwordTouched) && !passwordOk;
  const confirmInvalid = (submitted && !confirmPassword) || confirmMismatch;

  const canSubmit =
    isValidEmployeeId(empId) &&
    name.trim() &&
    dept &&
    passwordOk &&
    passwordsMatch &&
    !confirmMismatch &&
    !empStatus?.registered &&
    !deptsLoading &&
    departments.length > 0;

  const onSubmit = async (e) => {
    e.preventDefault();
    setSubmitted(true);
    setPasswordTouched(true);
    setFormError("");
    setPasswordServerError("");
    if (!canSubmit) return;

    setLoading(true);
    try {
      await signup({
        empId: empId.trim(),
        name: name.trim(),
        dept,
        password,
      });
      navigate("/generator", { replace: true });
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
          <form className="rc-login__form" onSubmit={onSubmit} noValidate>
            <div className="rc-login__brand">
              <AuthLogo size={36} />
              <h1>Create account</h1>
              <p>Register using your employee details</p>
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
                {verifiedEmployee.dept ? (
                  <div className="rc-login__verified-row">
                    <span className="rc-login__verified-label">Department</span>
                    <span className="rc-login__verified-value">{verifiedEmployee.dept}</span>
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

            {!deptLocked ? (
              <div className="rc-login__field">
                <label className="rc-login__label" htmlFor="dept">
                  Department
                </label>
                <Dropdown
                  id="dept"
                  value={dept}
                  options={departments}
                  optionLabel="label"
                  optionValue="value"
                  onChange={(e) => setDept(e.value)}
                  placeholder={deptsLoading ? "Loading…" : "Select department"}
                  disabled={loading || deptsLoading || departments.length === 0}
                  className={deptInvalid ? "p-invalid w-full" : "w-full"}
                  emptyMessage="No departments available"
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
                onChange={(e) => setPassword(sanitizeInput(e.target.value, "password").value)}
                placeholder="Enter password"
                feedback={false}
                toggleMask
                autoComplete="new-password"
                disabled={loading}
                className={passwordInvalid ? "p-invalid w-full" : "w-full"}
                inputClassName="w-full"
              />
            </div>

            <div className="rc-login__field">
              <label className="rc-login__label" htmlFor="confirmPassword">
                Confirm Password
              </label>
              <Password
                id="confirmPassword"
                value={confirmPassword}
                onChange={(e) =>
                  setConfirmPassword(sanitizeInput(e.target.value, "password").value)
                }
                placeholder="Confirm password"
                feedback={false}
                toggleMask
                autoComplete="new-password"
                disabled={loading}
                className={confirmInvalid ? "p-invalid w-full" : "w-full"}
                inputClassName="w-full"
              />
            </div>

            <Button
              type="submit"
              label={loading ? "Creating account..." : "Create account"}
              className="rc-login__cta"
              loading={loading}
              disabled={loading}
            />

            <p className="rc-login__hint">
              Already registered? <Link to="/login">Sign in</Link>
              <br />
              <Link to="/about">About the app</Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
