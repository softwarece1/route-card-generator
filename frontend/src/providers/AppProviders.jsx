import { useEffect } from 'react';
import { PrimeReactProvider } from 'primereact/api';
import { ConfirmDialog } from 'primereact/confirmdialog';
import { Toaster } from 'react-hot-toast';

import { ThemeProvider } from '@/providers/ThemeProvider';

import 'primeicons/primeicons.css';
import 'primeflex/primeflex.css';
import '@/styles/tokens.scss';
import '@/pages/login.scss';

const PRIME = {
  ripple: true,
  inputStyle: 'outlined',
};

export default function AppProviders({ children }) {
  useEffect(() => {
    document.body.classList.add('pmf-compact');
    return () => document.body.classList.remove('pmf-compact');
  }, []);

  return (
    <ThemeProvider>
      <PrimeReactProvider value={PRIME}>
        <Toaster
          position="top-right"
          toastOptions={{
            className: 'rc-hot-toast',
            style: {
              fontSize: '0.875rem',
              maxWidth: '26rem',
              padding: '0.75rem 1rem',
            },
          }}
          containerStyle={{ top: 16, right: 16, zIndex: 99999 }}
        />
        <ConfirmDialog className="p-confirm-dialog-sm" />
        {children}
      </PrimeReactProvider>
    </ThemeProvider>
  );
}
