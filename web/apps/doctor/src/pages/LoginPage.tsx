// Google sign-in for clinicians. The layout is the shared AuthShell and the
// interaction state is the shared useSignIn hook — this page exists for the two auth
// guards below, which are the only part that is genuinely per-portal.
//
// Guard order is load-bearing and must stay in this order: `initializing` first, then an
// already-signed-in user, and only then any markup. Rendering the shell above the second
// guard would flash a login screen at somebody who is already authenticated.

import { Navigate } from "react-router-dom";

import {
  AUTH_ACTION_CLASS,
  AuthShell,
  Button,
  LoadingScreen,
  signInActionLabel,
  useAuth,
  useSignIn,
} from "@pulseos/ui";

import { LOGIN_COPY } from "../login/view";

export function LoginPage() {
  const { user, initializing } = useAuth();
  const { busy, error, start } = useSignIn();

  if (initializing) {
    return <LoadingScreen message={LOGIN_COPY.checkingSession} />;
  }
  if (user !== null) {
    return <Navigate to="/" replace />;
  }

  return (
    <AuthShell portalName={LOGIN_COPY.portalName} subtitle={LOGIN_COPY.subtitle} error={error}>
      <Button type="button" className={AUTH_ACTION_CLASS} onClick={start} disabled={busy}>
        {signInActionLabel(busy)}
      </Button>
    </AuthShell>
  );
}
