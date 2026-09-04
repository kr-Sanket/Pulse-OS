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
import { PatientRecordsPage } from "./pages/PatientRecordsPage";
import { PatientSearchPage } from "./pages/PatientSearchPage";
import { RecordDetailPage } from "./pages/RecordDetailPage";
import { ProfilePage } from "./pages/ProfilePage";
import { RegisterPage } from "./pages/RegisterPage";
import { RequestsPage } from "./pages/RequestsPage";

export function App() {
  return (
    <AuthContextProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          {/* Onboarding needs a signed-in account but no clinician profile, so it sits
              behind the guard and outside the navigation shell. */}
          <Route
            path="/register"
            element={
              <ProtectedRoute>
                <RegisterPage />
              </ProtectedRoute>
            }
          />
          <Route
            element={
              <ProtectedRoute>
                <DoctorLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/patients" element={<PatientSearchPage />} />
            {/* Addressed by Health ID so the page is shareable and survives a reload;
                nothing has to be carried across the navigation from the search. */}
            <Route path="/patients/:healthId/records" element={<PatientRecordsPage />} />
            {/* Addressed by record id alone: the patient rides in navigation state for
                the Back link only, so a pasted URL still opens the record. */}
            <Route path="/records/:recordId" element={<RecordDetailPage />} />
            <Route path="/requests" element={<RequestsPage />} />
            <Route path="/profile" element={<ProfilePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthContextProvider>
  );
}
