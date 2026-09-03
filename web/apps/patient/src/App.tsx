// Patient portal routes.
//
// /login is public. Everything else renders inside PatientLayout behind ProtectedRoute:
// the guard wraps the layout once, so each page below is a plain <Outlet /> child and no
// page repeats the auth check. ProfilePage keeps its own behaviour and now lives at
// /profile, reachable from the sidebar.

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { PatientLayout } from "./components/layout/PatientLayout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AuditPage } from "./pages/AuditPage";
import { ConsentPage } from "./pages/ConsentPage";
import { DashboardPage } from "./pages/DashboardPage";
import { GrantsPage } from "./pages/GrantsPage";
import { LoginPage } from "./pages/LoginPage";
import { ProfilePage } from "./pages/ProfilePage";
import { RecordsPage } from "./pages/RecordsPage";
import { SettingsPage } from "./pages/SettingsPage";

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <ProtectedRoute>
                <PatientLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/records" element={<RecordsPage />} />
            <Route path="/consent" element={<ConsentPage />} />
            <Route path="/grants" element={<GrantsPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
