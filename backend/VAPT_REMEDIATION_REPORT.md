# VAPT Security Remediation Report

**Date:** 2026-10-26  
**Branch:** `security/vapt-remediation`  
**Application Stack:** FastAPI, Python 3.11, PostgreSQL / Pony ORM, Vite + React  

---

## 1. Executive Summary

This remediation report outlines the comprehensive security enhancements implemented to satisfy Vulnerability Assessment and Penetration Testing (VAPT) and OWASP Top 10 requirements for the Route Card Generator application. All controls have been integrated directly into the existing application architecture without breaking existing business logic or requiring architectural replacements.

---

## 2. Remediated Vulnerabilities & Implemented Controls

### 2.1 Server-Side Offline CAPTCHA Protection
- **Module:** [`backend/app/captcha.py`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/backend/app/captcha.py)
- **Endpoint:** `GET /api/v1/auth/captcha`
- **Verification Flow:** Integrated directly into `POST /api/v1/auth/login`.
- **Security Features:**
  - Fully offline server-side generation using Pillow (PIL) and cryptographically secure random tokens (`secrets.choice`).
  - Distorted noise lines and variable positioning to prevent simple OCR-based bypasses.
  - Secret-salted SHA-256 challenge hash stored in an in-memory `TTLCache` bounded by `CAPTCHA_TTL_SECONDS` (120s).
  - Enforced single-use validation (consumed upon successful verification or when exceeding `CAPTCHA_ATTEMPT_LIMIT`).

### 2.2 Rate Limiting
- **Module:** [`backend/app/middleware/rate_limit.py`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/backend/app/middleware/rate_limit.py)
- **Framework:** `SlowAPI` (wrapping `limits` library).
- **Controls Enforced:**
  - `POST /api/v1/auth/login`: Rate-limited by remote IP address (`RATE_LIMIT_LOGIN = "5/min"`).
  - `GET /api/v1/auth/captcha`: Rate-limited by remote IP address (`RATE_LIMIT_CAPTCHA = "10/min"`).
  - Automatically triggers HTTP `429 Too Many Requests` when thresholds are exceeded.

### 2.3 JWT Security, Idle Timeout & Token Revocation
- **Module:** [`backend/app/middleware/idle_timeout.py`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/backend/app/middleware/idle_timeout.py) & [`backend/app/auth.py`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/backend/app/auth.py)
- **Controls Enforced:**
  - Every access token includes a unique, cryptographically random `jti` (JWT ID) claim (`secrets.token_urlsafe(16)`).
  - **Server-Side Idle Inactivity Tracking:** `IdleSessionMiddleware` inspects bearer tokens on all protected requests. If inactivity exceeds `IDLE_TIMEOUT_MINUTES` (15 min), the token is automatically revoked, and HTTP 401 is returned.
  - **Logout Endpoint:** `POST /api/v1/auth/logout` explicitly adds the token's `jti` to the revocation store.
  - **Revocation Check in Authentication:** `get_current_user` verifies each token's `jti` against the revocation list before authorizing access.
  - *Multi-worker consideration:* The current implementation utilizes an in-memory store suitable for standalone and single-process deployments. For multi-worker deployments (e.g., Gunicorn/Uvicorn cluster), backing the revocation set with a centralized Redis instance is recommended.

### 2.4 Strict File Upload Validation & Path Traversal Hardening
- **Module:** [`backend/app/route_card/service.py`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/backend/app/route_card/service.py) (`read_upload`)
- **Controls Enforced:**
  - **Filename Sanitization:** Path traversal sequences (`..`, `/`, `\`) are strictly stripped.
  - **Double Extension Rejection:** File names containing secondary or hidden executable/script extensions (e.g., `.pdf.exe`, `.xlsx.vbs`, `.sh.tif`) are immediately rejected with HTTP 400.
  - **MIME Type Validation:** Client-provided `Content-Type` headers are checked against strict allow-lists mapped to legitimate extensions.
  - **File Magic Byte Verification:** Verifies file content signatures directly from binary headers (`%PDF-` for PDF, `II*` / `MM*` for TIFF, `PK\x03\x04` for XLSX, OLE CFB for XLS).
  - **Dynamic Size Limits:** Enforces `MAX_UPLOAD_SIZE_MB` (default 10 MB).

### 2.5 Enterprise Password Policy & Breach List Checking
- **Module:** [`backend/app/password_policy.py`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/backend/app/password_policy.py)
- **Controls Enforced:**
  - Length constraint: Minimum 12 characters, maximum 64 characters.
  - Character complexity: Requires at least one uppercase letter, one lowercase letter, one digit, and one special character.
  - Known-breach checking: Cross-referenced against a dictionary list of common and compromised passwords (`backend/data/common_passwords.txt`).
  - Enforced server-side during user registration (`POST /api/v1/auth/signup`).

### 2.6 Security Headers & Restricted CORS
- **Modules:** [`backend/app/middleware/security_headers.py`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/backend/app/middleware/security_headers.py) & [`backend/app/main.py`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/backend/app/main.py)
- **Headers Added to All Responses:**
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; frame-ancestors 'none';`
- **CORS Hardening:** Removed permissive wildcard (`allow_origins=["*"]`) and replaced with configured origin list (`settings.CORS_ORIGINS`).

---

## 3. Configuration Variables Added

The following variables have been added to [`backend/app/config/settings.py`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/backend/app/config/settings.py) and can be customized via `.env`:

| Variable | Default Value | Description |
|---|---|---|
| `CAPTCHA_TTL_SECONDS` | `120` | Lifetime in seconds for a CAPTCHA challenge |
| `CAPTCHA_ATTEMPT_LIMIT` | `5` | Maximum failed attempts allowed per CAPTCHA |
| `RATE_LIMIT_LOGIN` | `"5/min"` | Maximum login attempts per remote IP per minute |
| `RATE_LIMIT_CAPTCHA` | `"30/min"` | Maximum CAPTCHA requests per remote IP per minute |
| `IDLE_TIMEOUT_MINUTES` | `15` | Inactivity threshold before session invalidation |
| `MAX_UPLOAD_SIZE_MB` | `10` | Maximum upload size in megabytes |
| `COMMON_PASSWORDS_PATH` | `"backend/data/common_passwords.txt"` | Path to common passwords blacklist file |
| `CORS_ORIGINS` | `["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174"]` | Whitelist of origins permitted to make cross-origin requests |

---

## 4. Frontend UI & Integration

- **Component:** [`frontend/src/pages/LoginPage.jsx`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/frontend/src/pages/LoginPage.jsx) & [`frontend/src/pages/login.scss`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/frontend/src/pages/login.scss)
- **API Client:** [`frontend/src/services/authApi.js`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/frontend/src/services/authApi.js) & [`frontend/src/lib/credCrypto.js`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/frontend/src/lib/credCrypto.js)
- **Implemented UI Elements:**
  - Dynamic CAPTCHA image challenge display with base64 PNG data rendering.
  - Refresh button (`pi pi-refresh`) requesting a fresh challenge on demand.
  - Loading spinner state during initial fetch and challenge refresh.
  - `Enter CAPTCHA` input field with client-side sanitization and error states.
  - Automatic challenge re-fetch upon unsuccessful authentication attempts.
  - Dual RSA-encrypted payload delivery preserving end-to-end credential privacy.

---

## 5. Test Verification & Results

Automated security test suite created in [`backend/tests/test_security.py`](file:///e:/PMF/route-card-generator-main/route-card-generator-main/backend/tests/test_security.py).

### Execution Command:
```powershell
cd backend
.\venv\Scripts\python.exe -m pytest -v tests/test_security.py
```

### Test Results:
```text
======= 7 passed, 1 warning in 7.73s =======
```

**Test Coverage Highlights:**
- `test_security_headers_present`: Verifies `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Content-Security-Policy`.
- `test_cors_headers_strict`: Verifies explicit allowed origins and rejection of untrusted origins.
- `test_captcha_generation_and_verification`: Verifies PNG generation, endpoint payload, and attempt invalidation.
- `test_password_policy_enforcement`: Tests length, character composition rules, and common password dictionary blocks.
- `test_upload_file_hardening`: Verifies rejection of double extensions, invalid MIME types, and non-conforming file headers.
- `test_jwt_session_idle_and_revocation`: Verifies `jti` inclusion, explicit logout revocation, and rejection of invalidated tokens.
- `test_login_captcha_scenarios`: Tests challenge refresh, missing CAPTCHA blocking, invalid CAPTCHA rejection, single-use invalidation, and successful authenticated login with valid credentials.

---

## 5. Startup & Run Instructions

### 1. Backend Service
```powershell
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8008
```

### 2. Frontend Service
```powershell
cd frontend
npm run dev
```
