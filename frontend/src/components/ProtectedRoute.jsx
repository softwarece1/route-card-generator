import { useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { clearAuth, isAuthenticated, setAuth } from '@/lib/auth';
import { fetchMe } from '@/services/authApi';

export default function ProtectedRoute({ children }) {
  const location = useLocation();
  const [ready, setReady] = useState(() => isAuthenticated());
  const [allowed, setAllowed] = useState(() => isAuthenticated());

  useEffect(() => {
    let cancelled = false;
    if (isAuthenticated()) {
      setAllowed(true);
      setReady(true);
      return undefined;
    }
    // Cookie may still be valid after cleared profile storage
    fetchMe()
      .then((user) => {
        if (cancelled) return;
        if (user) {
          setAuth(null, user);
          setAllowed(true);
        } else {
          clearAuth();
          setAllowed(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          clearAuth();
          setAllowed(false);
        }
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return null;
  }
  if (!allowed) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return children;
}
