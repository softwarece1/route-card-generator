import { useState, useEffect, useCallback } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Button } from "primereact/button";
import { Dialog } from "primereact/dialog";
import { Password } from "primereact/password";
import { isAuthenticated } from "@/lib/auth";
import { sanitizeInput } from "@/lib/inputSafe";
import { fetchCaptcha, login } from "@/services/authApi";
import AuthLogo from "@/components/AuthLogo";
import SafeInputText from "@/components/SafeInputText";
import ThemeToggle from "@/components/ThemeToggle";
import heroImg from "@/assets/hero.png";
import "./login.scss";

export default function LoginPage() {
  const navigate = useNavigate();
  const [empId, setEmpId] = useState("");
  const [password, setPassword] = useState("");
  const [captchaId, setCaptchaId] = useState("");
  const [captchaImg, setCaptchaImg] = useState("");
  const [captchaAnswer, setCaptchaAnswer] = useState("");
  const [captchaLoading, setCaptchaLoading] = useState(false);
  const [captchaError, setCaptchaError] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [formError, setFormError] = useState("");
  const [forgotOpen, setForgotOpen] = useState(false);

  const loadCaptcha = useCallback(async () => {
    setCaptchaLoading(true);
    setCaptchaError("");
    try {
      const data = await fetchCaptcha();
      setCaptchaId(data.captchaId);
      setCaptchaImg(data.imageData);
      setCaptchaAnswer("");
    } catch (err) {
      setCaptchaError("Failed to load CAPTCHA. Click refresh to retry.");
    } finally {
      setCaptchaLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCaptcha();
  }, [loadCaptcha]);

  if (isAuthenticated()) {
    return <Navigate to="/generator" replace />;
  }

  const empInvalid = submitted && !empId.trim();
  const passwordInvalid = submitted && !password;
  const captchaInvalid = submitted && !captchaAnswer.trim();

  const onSubmit = async (e) => {
    e.preventDefault();
    setSubmitted(true);
    setFormError("");
    if (!empId.trim() || !password) return;
    if (!captchaAnswer.trim()) {
      setFormError("Please enter the CAPTCHA code");
      return;
    }

    setLoading(true);
    try {
      await login(empId.trim(), password, captchaId, captchaAnswer.trim());
      navigate("/generator", { replace: true });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setFormError(
        typeof detail === "string" ? detail : err?.message || "Sign in failed"
      );
      loadCaptcha();
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
              <h1>Automated OARC Generator</h1>
              <p>Sign in with your employee ID</p>
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
                  setEmpId(e.target.value);
                  if (formError) setFormError("");
                }}
                placeholder="Enter employee ID"
                autoComplete="username"
                disabled={loading}
                className={empInvalid ? "p-invalid" : undefined}
                aria-invalid={empInvalid}
                maxLength={64}
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
                  setPassword(sanitizeInput(e.target.value, "password").value);
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

            <div className="rc-login__field rc-login__captcha-field">
              <label className="rc-login__label" htmlFor="captchaAnswer">
                Enter CAPTCHA
              </label>
              <div className="rc-login__captcha-challenge">
                <div className="rc-login__captcha-img-box" aria-label="CAPTCHA Challenge">
                  {captchaLoading ? (
                    <div className="rc-login__captcha-loading">
                      <i className="pi pi-spin pi-spinner" style={{ fontSize: "1.1rem" }} />
                      <span>Loading code...</span>
                    </div>
                  ) : captchaImg ? (
                    <img
                      src={captchaImg}
                      alt="CAPTCHA code challenge"
                      className="rc-login__captcha-img"
                    />
                  ) : (
                    <span className="rc-login__captcha-fallback">
                      {captchaError || "CAPTCHA unavailable"}
                    </span>
                  )}
                </div>
                <Button
                  type="button"
                  icon="pi pi-refresh"
                  className="rc-login__captcha-refresh"
                  onClick={loadCaptcha}
                  disabled={loading || captchaLoading}
                  tooltip="Refresh CAPTCHA"
                  tooltipOptions={{ position: "top" }}
                  aria-label="Refresh CAPTCHA challenge"
                />
              </div>
              <SafeInputText
                id="captchaAnswer"
                profile="text"
                value={captchaAnswer}
                onChange={(e) => {
                  setCaptchaAnswer(e.target.value);
                  if (formError) setFormError("");
                }}
                placeholder="Enter CAPTCHA"
                autoComplete="off"
                disabled={loading || captchaLoading}
                className={captchaInvalid ? "p-invalid" : undefined}
                aria-invalid={captchaInvalid}
                maxLength={12}
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
              <Link to="/about">About the app</Link>
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
