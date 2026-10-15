// Route guard: unauthenticated users go to /login; while Firebase restores the
// session we show a loading screen instead of flashing the login page.

import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { useAuth } from "../auth/AuthContext";
import { LoadingScreen } from "./LoadingScreen";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, initializing } = useAuth();
  const location = useLocation();

  if (initializing) {
    return <LoadingScreen message="Checking your session…" />;
  }
  if (user === null) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <>{children}</>;
}
