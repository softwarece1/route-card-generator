/** Client auth state — user profile only; access JWT lives in httpOnly cookie. */

const USER_KEY = 'rc_user';
const AUTH_FLAG_KEY = 'rc_authed';

export function getToken() {
  // Access token is httpOnly; never stored in JS. Kept for API compat (always empty).
  return '';
}

export function getUser() {
  try {
    const raw = sessionStorage.getItem(USER_KEY) || localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function isAuthenticated() {
  if (getUser()) return true;
  try {
    return sessionStorage.getItem(AUTH_FLAG_KEY) === '1'
      || localStorage.getItem(AUTH_FLAG_KEY) === '1';
  } catch {
    return false;
  }
}

/** @param {string|null|undefined} _token ignored (cookie-based) */
export function setAuth(_token, user) {
  const payload = JSON.stringify(user || {});
  try {
    sessionStorage.setItem(USER_KEY, payload);
    sessionStorage.setItem(AUTH_FLAG_KEY, '1');
    localStorage.setItem(USER_KEY, payload);
    localStorage.setItem(AUTH_FLAG_KEY, '1');
    localStorage.removeItem('rc_token');
  } catch {
    /* ignore quota */
  }
}

export function clearAuth() {
  try {
    sessionStorage.removeItem(USER_KEY);
    sessionStorage.removeItem(AUTH_FLAG_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(AUTH_FLAG_KEY);
    localStorage.removeItem('rc_token');
  } catch {
    /* ignore */
  }
}
