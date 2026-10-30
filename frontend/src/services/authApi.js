import http from '@/lib/http';
import { setAuth, clearAuth, getUser } from '@/lib/auth';
import { encryptCredentials } from '@/lib/credCrypto';
import { sanitizeInput } from '@/lib/inputSafe';

let publicKeyPromise = null;

async function fetchPublicKey() {
  if (!publicKeyPromise) {
    publicKeyPromise = http
      .get('/auth/public-key')
      .then(({ data }) => data)
      .catch((err) => {
        publicKeyPromise = null;
        throw err;
      });
  }
  return publicKeyPromise;
}

export async function fetchCaptcha() {
  const { data } = await http.get('/auth/captcha');
  return data;
}

async function encryptedCredsBody(empId, password, captchaId, captchaAnswer) {
  const keyInfo = await fetchPublicKey();
  const safeEmp = sanitizeInput(empId, 'empId').value;
  const safePass = sanitizeInput(password, 'password').value;
  const safeCaptchaAnswer = sanitizeInput(captchaAnswer || '', 'text').value;
  return encryptCredentials(keyInfo, {
    empId: safeEmp,
    password: safePass,
    captchaId: captchaId || '',
    captchaAnswer: safeCaptchaAnswer,
  });
}

export async function login(empId, password, captchaId, captchaAnswer, options = {}) {
  const body = await encryptedCredsBody(empId, password, captchaId, captchaAnswer);
  const { data } = await http.post('/auth/login', {
    ...body,
    captchaId: captchaId || '',
    captchaAnswer: (captchaAnswer || '').trim(),
    terminateExistingSession: Boolean(options.terminateExistingSession),
    resumeToken: options.resumeToken || undefined,
  });
  setAuth(data.access_token, data.user);
  return data;
}

/** After concurrent-session 409: end the other session and use this browser. */
export async function takeoverSession(resumeToken) {
  const { data } = await http.post('/auth/login/takeover', {
    resumeToken: (resumeToken || '').trim(),
  });
  setAuth(data.access_token, data.user);
  return data;
}

/** Parse FastAPI 409 concurrent-session payload from a login error. */
export function concurrentSessionFromError(err) {
  const detail = err?.response?.data?.detail;
  if (err?.response?.status !== 409) return null;
  if (detail && typeof detail === 'object' && detail.code === 'CONCURRENT_SESSION') {
    return {
      message:
        detail.message ||
        'This account is already signed in elsewhere. Terminate that session to continue here?',
      resumeToken: detail.resumeToken || '',
    };
  }
  return null;
}

export async function signup({ empId, name, dept, password }) {
  const { cipher, alg } = await encryptedCredsBody(empId, password);
  const safeName = sanitizeInput(name, 'personName').value;
  const safeDept = sanitizeInput(dept, 'label').value;
  const { data } = await http.post('/auth/signup', {
    name: safeName,
    dept: safeDept,
    cipher,
    alg,
  });
  setAuth(data.access_token, data.user);
  return data;
}

export async function fetchMe() {
  const { data } = await http.get('/auth/me');
  return data;
}

/** Department master for signup dropdown. */
export async function fetchDepartments() {
  const { data } = await http.get('/auth/departments');
  return Array.isArray(data) ? data : [];
}

/**
 * Signup helper: whether empId is already registered.
 * `employee` is populated only when an Employee Master exists (none today).
 */
export async function fetchEmpStatus(empId) {
  const id = encodeURIComponent((empId || '').trim());
  if (!id) {
    return {
      empId: '',
      registered: false,
      available: false,
      verified: false,
      employee: null,
    };
  }
  const { data } = await http.get(`/auth/emp-status/${id}`);
  return data;
}

export async function changePassword({ currentPassword, newPassword }) {
  const { data } = await http.post('/auth/change-password', {
    currentPassword,
    newPassword,
  });
  if (data?.user) {
    const token = localStorage.getItem('rc_token') || '';
    setAuth(token, data.user);
  }
  return data;
}

export function logout() {
  clearAuth();
  publicKeyPromise = null;
}

export { getUser };
