import { Navigate, Route, Routes } from 'react-router-dom';
import ProtectedRoute from '@/components/ProtectedRoute';
import { getUser, isAuthenticated } from '@/lib/auth';
import LoginPage from '@/pages/LoginPage';
import SignupPage from '@/pages/SignupPage';
import ExtractionsPage from '@/pages/ExtractionsPage';
import OperationTemplatesPage from '@/pages/OperationTemplatesPage';
import UploadsPage from '@/pages/UploadsPage';
import UsersPage from '@/pages/UsersPage';
import AboutPage from '@/pages/AboutPage';
import RouteCardGenerationAlt from '@/pages/RouteCardGenerationAlt';
import SystemPage from '@/pages/SystemPage';
import WorkCentersPage from '@/pages/WorkCentersPage';
import OrgStructurePage from '@/pages/OrgStructurePage';
import ReferenceSheetsPage from '@/pages/ReferenceSheetsPage';

/** `/` → IED review queue, else generator when signed in; otherwise login. */
function HomeRedirect() {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  const u = getUser();
  if (u?.isIedDept || u?.role === "ied") return <Navigate to="/history" replace />;
  return <Navigate to="/generator" replace />;
}

function IedBlockGenerator({ children }) {
  const u = getUser();
  if (u?.isIedDept || u?.role === "ied") return <Navigate to="/history" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomeRedirect />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/about" element={<AboutPage />} />
      <Route
        path="/generator"
        element={
          <ProtectedRoute>
            <IedBlockGenerator>
              <RouteCardGenerationAlt />
            </IedBlockGenerator>
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
      <Route
        path="/work-centers"
        element={
          <ProtectedRoute>
            <WorkCentersPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/reference-sheets"
        element={
          <ProtectedRoute>
            <ReferenceSheetsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/org"
        element={
          <ProtectedRoute>
            <OrgStructurePage />
          </ProtectedRoute>
        }
      />
      <Route path="/new" element={<Navigate to="/" replace />} />
      <Route path="/classic" element={<Navigate to="/" replace />} />
      <Route path="*" element={<HomeRedirect />} />
    </Routes>
  );
}
