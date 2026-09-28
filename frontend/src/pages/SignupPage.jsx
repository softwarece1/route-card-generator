import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "primereact/button";
import { InputText } from "primereact/inputtext";
import { Password } from "primereact/password";
import { Dropdown } from "primereact/dropdown";
import {
  signup,
  fetchDepartments,
  fetchEmpStatus,
} from "@/services/authApi";
import AuthLogo from "@/components/AuthLogo";
import heroImg from "@/assets/hero.png";
import "./login.scss";

const MIN_PASSWORD = 4;

export default function SignupPage() {
  const navigate = useNavigate();
  const empCheckSeq = useRef(0);

  const [empId, setEmpId] = useState("");
  const [name, setName] = useState("");
  const [dept, setDept] = useState(null);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
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

  const passwordOk = password.length >= MIN_PASSWORD;
  const passwordsMatch = password.length > 0 && password === confirmPassword;
  const nameLocked = Boolean(verifiedEmployee?.name);
  const deptLocked = Boolean(verifiedEmployee?.dept);

  const empInvalid =
    submitted && (!empId.trim() || Boolean(empStatus?.registered));
  const nameInvalid = submitted && !name.trim() && !nameLocked;
  const deptInvalid = submitted && !dept && !deptLocked;
  const passwordInvalid = submitted && (!password || !passwordOk);
  const confirmInvalid = submitted && (!confirmPassword || !passwordsMatch);

  const canSubmit =
    empId.trim() &&
    name.trim() &&
    dept &&
    passwordOk &&
    passwordsMatch &&
    !empStatus?.registered &&
    !deptsLoading &&
    departments.length > 0;

  const onSubmit = async (e) => {
    e.preventDefault();
    setSubmitted(true);
    setFormError("");
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
      setFormError(
        typeof detail === "string" ? detail : err?.message || "Could not create account"
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rc-login">
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
              <InputText
                id="empId"
                value={empId}
                onChange={(e) => {
                  setEmpId(e.target.value);
                  setEmpStatus(null);
                  setVerifiedEmployee(null);
                  if (formError) setFormError("");
                }}
                onBlur={() => checkEmpId(empId)}
                placeholder="Enter employee ID"
                autoComplete="username"
                disabled={loading}
                className={empInvalid ? "p-invalid" : undefined}
                aria-invalid={empInvalid}
              />
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
                <InputText
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Enter full name"
                  autoComplete="name"
                  disabled={loading}
                  className={nameInvalid ? "p-invalid" : undefined}
                  aria-invalid={nameInvalid}
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
                onChange={(e) => setPassword(e.target.value)}
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
                onChange={(e) => setConfirmPassword(e.target.value)}
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
              <Link to="/">Back to home</Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
