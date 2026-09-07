// The sign-in interaction state, shared by the three portals' login pages.
//
// This is the third copy of a `busy`/`error` pair that was written out by hand in each
// portal, hoisted rather than copied again. It changes no authentication semantics: it
// calls the same `signIn()` off the same context, which is still Firebase's
// `signInWithPopup` with a `GoogleAuthProvider` behind auth/provider.ts. No new mechanism,
// no credentials, no provider configuration.
//
// Two behaviours here are deliberate and match what the pages did before:
//
//   • The provider's error never reaches the UI. Firebase reports a user closing the popup
//     the same way it reports a misconfigured project, and neither is useful — or safe — to
//     put on screen, so every failure becomes one sanitized sentence.
//   • `busy` is cleared only on failure. A successful sign-in changes the auth state, and
//     the page redirects on that; clearing it would flash the idle label on the way out.
//
// It owns no navigation. The already-signed-in redirect stays in each page, above the
// markup, where the guard order can be read in one place.

import { useCallback, useState } from "react";

import { useAuth } from "./AuthContext";

/** The only failure text any portal shows. Provider detail is deliberately discarded. */
export const SIGN_IN_FAILED = "Sign-in did not complete. Please try again.";

export interface SignIn {
  /** A sign-in is in flight, or has succeeded and the redirect has not happened yet. */
  busy: boolean;
  /** A sanitized message, or null. */
  error: string | null;
  /** Start the popup flow. Safe to hand straight to onClick — it returns no promise. */
  start: () => void;
}

export function useSignIn(): SignIn {
  const { signIn } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(() => {
    setBusy(true);
    setError(null);
    void (async () => {
      try {
        await signIn();
      } catch {
        setError(SIGN_IN_FAILED);
        setBusy(false);
      }
    })();
  }, [signIn]);

  return { busy, error, start };
}
