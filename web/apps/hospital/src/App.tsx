// Hospital portal routes.
//
// /login is public. Everything else renders inside HospitalLayout behind ProtectedRoute:
// the guard wraps the layout once, so each page below is a plain <Outlet /> child and no
// page repeats the auth check.

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthContextProvider, ProtectedRoute } from "@pulseos/ui";

import { AdminLayout } from "./admin/AdminLayout";
import { AdminDashboardPage } from "./pages/AdminDashboardPage";
import { AuditPage } from "./pages/AuditPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DoctorsPage } from "./pages/DoctorsPage";
import { HospitalLayout } from "./components/layout/HospitalLayout";
import { HospitalPage } from "./pages/HospitalPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { SystemAdminVerificationPage } from "./pages/SystemAdminVerificationPage";
import { UploadDetailPage } from "./pages/UploadDetailPage";
import { UploadPage } from "./pages/UploadPage";
import { UploadsPage } from "./pages/UploadsPage";

export function App() {
  return (
    <AuthContextProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          {/* Onboarding needs a signed-in account but no hospital, so it sits behind the
              guard and outside the navigation shell. */}
          <Route
            path="/register"
            element={
              <ProtectedRoute>
                <RegisterPage />
              </ProtectedRoute>
            }
          />
          {/* Dedicated System Admin experience */}
          <Route
            element={
              <ProtectedRoute>
                <AdminLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/admin" element={<AdminDashboardPage />} />
            <Route path="/admin/dashboard" element={<Navigate to="/admin" replace />} />
            <Route path="/admin/verification" element={<SystemAdminVerificationPage />} />
          </Route>
          {/* "/" is the canonical dashboard URL and "/dashboard" is the spelling people type.
              Redirecting rather than rendering the page twice keeps one URL authoritative, so
              the sidebar's active state, the top-bar title and the browser history cannot
              disagree about where the user is. */}
          <Route path="/dashboard" element={<Navigate to="/" replace />} />
          <Route
            element={
              <ProtectedRoute>
                <HospitalLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/doctors" element={<DoctorsPage />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/uploads" element={<UploadsPage />} />
            {/* Addressed by record id alone, so a pasted URL still opens the record. */}
            <Route path="/uploads/:recordId" element={<UploadDetailPage />} />
            <Route path="/hospital" element={<HospitalPage />} />
            <Route path="/audit" element={<AuditPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthContextProvider>
  );
}
