// Route guard: unauthenticated users go to /login; while Firebase restores the
// session we show a loading screen instead of flashing the login page.

import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";

import { useAuth } from "../auth/AuthContext";
import { LoadingScreen } from "./LoadingScreen";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, initializing } = useAuth();
  if (initializing) {
    return <LoadingScreen message="Checking your session…" />;
  }
  if (user === null) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
