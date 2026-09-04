// Google sign-in for clinicians. Authentication itself is the shared provider — this page
// only renders the affordance and whatever went wrong.

import { HeartPulse } from "lucide-react";
import { useState } from "react";
import { Navigate } from "react-router-dom";

import { LoadingScreen, useAuth } from "@pulseos/ui";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

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
    <main className="bg-background flex min-h-svh items-center justify-center px-4">
      <Card className="w-full max-w-sm [--card-spacing:--spacing(6)]">
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2.5">
              <HeartPulse className="text-primary size-6" aria-hidden />
              <span className="text-[17px] font-semibold tracking-tight">PulseOS</span>
            </div>
            <h1 className="text-foreground text-xl font-semibold tracking-tight">Doctor portal</h1>
            <p className="text-muted-foreground text-sm leading-relaxed">
              Sign in with the Google account registered at your hospital.
            </p>
          </div>

          <Button
            type="button"
            className="w-full justify-center"
            onClick={() => void handleSignIn()}
            disabled={busy}
          >
            {busy ? "Signing in…" : "Continue with Google"}
          </Button>

          {error === null ? null : (
            <p role="alert" className="text-destructive text-sm leading-relaxed">
              {error}
            </p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
