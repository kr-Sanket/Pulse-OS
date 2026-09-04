// Doctor portal routes.
//
// /login is public. Everything else renders inside DoctorLayout behind ProtectedRoute:
// the guard wraps the layout once, so each page below is a plain <Outlet /> child and no
// page repeats the auth check.

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthContextProvider, ProtectedRoute } from "@pulseos/ui";

import { DoctorLayout } from "./components/layout/DoctorLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { PatientSearchPage } from "./pages/PatientSearchPage";

export function App() {
  return (
    <AuthContextProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <ProtectedRoute>
                <DoctorLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/patients" element={<PatientSearchPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthContextProvider>
  );
}
