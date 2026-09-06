// Hospital portal routes.
//
// /login is public. Everything else renders inside HospitalLayout behind ProtectedRoute:
// the guard wraps the layout once, so each page below is a plain <Outlet /> child and no
// page repeats the auth check.

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthContextProvider, ProtectedRoute } from "@pulseos/ui";

import { HospitalLayout } from "./components/layout/HospitalLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { HospitalPage } from "./pages/HospitalPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";

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
            <Route path="/hospital" element={<HospitalPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthContextProvider>
  );
}
