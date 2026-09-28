import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "primereact/button";
import { Dialog } from "primereact/dialog";
import { InputText } from "primereact/inputtext";
import { Password } from "primereact/password";
import { login } from "@/services/authApi";
import AuthLogo from "@/components/AuthLogo";
import heroImg from "@/assets/hero.png";
import "./login.scss";

export default function LoginPage() {
  const navigate = useNavigate();
  const [empId, setEmpId] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [formError, setFormError] = useState("");
  const [forgotOpen, setForgotOpen] = useState(false);

  const empInvalid = submitted && !empId.trim();
  const passwordInvalid = submitted && !password;

  const onSubmit = async (e) => {
    e.preventDefault();
    setSubmitted(true);
    setFormError("");
    if (!empId.trim() || !password) return;

    setLoading(true);
    try {
      await login(empId.trim(), password);
      navigate("/generator", { replace: true });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setFormError(
        typeof detail === "string" ? detail : err?.message || "Sign in failed"
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
              <h1>Automated OARC Generator</h1>
              <p>Sign in with your employee ID</p>
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
                  if (formError) setFormError("");
                }}
                placeholder="Enter employee ID"
                autoComplete="username"
                disabled={loading}
                className={empInvalid ? "p-invalid" : undefined}
                aria-invalid={empInvalid}
              />
            </div>

            <div className="rc-login__field">
              <div className="rc-login__label-row">
                <label className="rc-login__label" htmlFor="password">
                  Password
                </label>
                <button
                  type="button"
                  className="rc-login__forgot"
                  onClick={() => setForgotOpen(true)}
                >
                  Forgot password?
                </button>
              </div>
              <Password
                id="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (formError) setFormError("");
                }}
                placeholder="Enter password"
                feedback={false}
                toggleMask
                autoComplete="current-password"
                disabled={loading}
                className={passwordInvalid ? "p-invalid w-full" : "w-full"}
                inputClassName="w-full"
                aria-invalid={passwordInvalid}
              />
            </div>

            <Button
              type="submit"
              label={loading ? "Signing in..." : "Sign in"}
              className="rc-login__cta"
              loading={loading}
              disabled={loading}
            />

            <p className="rc-login__hint">
              New here? <Link to="/signup">Create an account</Link>
              <br />
              <Link to="/">Back to home</Link>
            </p>
          </form>
        </div>
      </div>

      <Dialog
        header="Forgot password"
        visible={forgotOpen}
        style={{ width: "min(26rem, 94vw)" }}
        modal
        onHide={() => setForgotOpen(false)}
        footer={
          <Button
            type="button"
            label="Got it"
            size="small"
            onClick={() => setForgotOpen(false)}
          />
        }
      >
        <p className="rc-login__forgot-copy">
          Engineers cannot reset their own password here. Ask your{" "}
          <strong>department head</strong> or an <strong>admin</strong> to reset it from the{" "}
          <strong>Users</strong> page (Reset password action).
        </p>
      </Dialog>
    </div>
  );
}
