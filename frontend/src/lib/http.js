import axios from 'axios';
import { clearAuth, getToken } from '@/lib/auth';

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || '/api/v1';

const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120_000,
});

http.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error?.response?.status === 401) {
      const detail = error?.response?.data?.detail;
      if (typeof detail === 'string' && /signed in elsewhere|another browser|session was ended/i.test(detail)) {
        try {
          sessionStorage.setItem('rc_auth_notice', detail);
        } catch {
          /* ignore */
        }
      }
      clearAuth();
      if (!window.location.pathname.startsWith('/login') && !window.location.pathname.startsWith('/signup')) {
        window.location.assign('/login');
      }
    }
    // Axios "Network Error" when backend is down or CORS blocked
    if (!error.response && error.message === 'Network Error') {
      error.message =
        'Cannot reach API. Is the backend running on port 8008?';
    }
    return Promise.reject(error);
  },
);

export default http;
