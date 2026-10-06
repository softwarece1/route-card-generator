import { Navigate, Route, Routes } from 'react-router-dom';
import ProtectedRoute from '@/components/ProtectedRoute';
import LoginPage from '@/pages/LoginPage';
import SignupPage from '@/pages/SignupPage';
import ExtractionsPage from '@/pages/ExtractionsPage';
import OperationTemplatesPage from '@/pages/OperationTemplatesPage';
import UploadsPage from '@/pages/UploadsPage';
import UsersPage from '@/pages/UsersPage';
import AboutPage from '@/pages/AboutPage';
import RouteCardGenerationAlt from '@/pages/RouteCardGenerationAlt';
import SystemPage from '@/pages/SystemPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<AboutPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route
        path="/generator"
        element={
          <ProtectedRoute>
            <RouteCardGenerationAlt />
          </ProtectedRoute>
        }
      />
      <Route
        path="/history"
        element={
          <ProtectedRoute>
            <ExtractionsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/system"
        element={
          <ProtectedRoute>
            <SystemPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/uploads"
        element={
          <ProtectedRoute>
            <UploadsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/users"
        element={
          <ProtectedRoute>
            <UsersPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/operation-templates"
        element={
          <ProtectedRoute>
            <OperationTemplatesPage />
          </ProtectedRoute>
        }
      />
      <Route path="/about" element={<Navigate to="/" replace />} />
      <Route path="/new" element={<Navigate to="/generator" replace />} />
      <Route path="/classic" element={<Navigate to="/generator" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
