import http from '@/lib/http';
import { setAuth, clearAuth, getUser } from '@/lib/auth';

export async function login(empId, password) {
  const { data } = await http.post('/auth/login', { empId, password });
  setAuth(data.access_token, data.user);
  return data;
}

export async function signup({ empId, name, dept, password }) {
  const { data } = await http.post('/auth/signup', { empId, name, dept, password });
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

export function logout() {
  clearAuth();
}

export { getUser };
