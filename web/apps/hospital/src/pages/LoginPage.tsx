// Google sign-in for hospital administrators. The layout is the shared AuthShell and the
// interaction state is the shared useSignIn hook — this page exists for the two auth
// guards below, which are the only part that is genuinely per-portal.
//
// Guard order is load-bearing and must stay in this order: `initializing` first, then an
// already-signed-in user, and only then any markup. Rendering the shell above the second
// guard would flash a login screen at somebody who is already authenticated.

import { Navigate, useLocation } from "react-router-dom";

import {
  AUTH_ACTION_CLASS,
  AuthShell,
  Button,
  LoadingScreen,
  signInActionLabel,
  useAuth,
  useSignIn,
} from "@pulseos/ui";

import {
  useCurrentUserRole,
  type CurrentUserRoleState,
} from "../components/layout/useCurrentUserRole";
import { getSafeRedirectPath } from "../login/redirect";
import { LOGIN_COPY } from "../login/view";

export interface LoginPageProps {
  useRole?: () => CurrentUserRoleState;
}

export function LoginPage({ useRole = useCurrentUserRole }: LoginPageProps = {}) {
  const { user, initializing } = useAuth();
  const { busy, error, start } = useSignIn();
  const location = useLocation();
  const { role, loading: roleLoading } = useRole();

  if (initializing) {
    return <LoadingScreen message={LOGIN_COPY.checkingSession} />;
  }
  if (user !== null) {
    const from = (location.state as { from?: unknown } | null)?.from;
    // If a specific destination was preserved (and isn't the root), honor it directly.
    if (from !== undefined && from !== null && from !== "/") {
      const destination = getSafeRedirectPath(from, "/");
      return <Navigate to={destination} replace />;
    }
    // For default landing destination, wait for the user's role to be confirmed from the backend.
    if (roleLoading) {
      return <LoadingScreen message={LOGIN_COPY.checkingSession} />;
    }
    const defaultDestination = role === "SYSTEM_ADMIN" ? "/admin" : "/";
    const destination = getSafeRedirectPath(from, defaultDestination);
    return <Navigate to={destination} replace />;
  }

  return (
    <AuthShell portalName={LOGIN_COPY.portalName} subtitle={LOGIN_COPY.subtitle} error={error}>
      <Button type="button" className={AUTH_ACTION_CLASS} onClick={start} disabled={busy}>
        {signInActionLabel(busy)}
      </Button>
    </AuthShell>
  );
}
