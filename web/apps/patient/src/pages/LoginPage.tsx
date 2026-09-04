import { useState } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "@pulseos/ui";
import { LoadingScreen } from "@pulseos/ui";

export function LoginPage() {
  const { user, initializing, signIn } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (initializing) {
    return <LoadingScreen message="Checking your session…" />;
  }
  if (user !== null) {
    return <Navigate to="/" replace />;
  }

  const handleSignIn = async () => {
    setBusy(true);
    setError(null);
    try {
      await signIn();
    } catch {
      // Firebase error details stay out of the UI; the common case is a closed popup.
      setError("Sign-in did not complete. Please try again.");
      setBusy(false);
    }
  };

  return (
    <main style={{ fontFamily: "system-ui", padding: "2rem" }}>
      <h1>PulseOS — Patient Portal</h1>
      <p>Sign in to see your Pulse Health ID and profile.</p>
      <button type="button" onClick={() => void handleSignIn()} disabled={busy}>
        {busy ? "Signing in…" : "Continue with Google"}
      </button>
      {error !== null && <p role="alert">{error}</p>}
    </main>
  );
}
