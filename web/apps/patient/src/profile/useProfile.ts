// The Profile page's one request, as a hook: run the bootstrap, expose its three states,
// and allow a retry.
//
// The work itself stays in loadProfile.ts — GET /patients/me, registering transparently on
// a 403 and retrying with a refreshed token. This file adds only the React lifecycle
// around it: the identity to register with, a token refresher built from the signed-in
// user, and a cancellation flag so a result cannot land after the page has gone.
//
// Deliberately not the records page's useApiResource: this is a multi-step bootstrap with
// no cursor, no abortable loader and no idle state, and loadProfile.ts takes no AbortSignal.

import { useEffect, useState } from "react";

import type { PatientProfile } from "@pulseos/api-client";

import { api } from "@/api";
import { useAuth } from "@/auth/AuthContext";

import { loadOrRegisterProfile } from "./loadProfile";

export type ProfileState =
  | { status: "loading" }
  | { status: "ready"; profile: PatientProfile }
  | { status: "error"; message: string };

export interface ProfileResource {
  state: ProfileState;
  reload: () => void;
}

export function useProfile(): ProfileResource {
  const { user } = useAuth();
  const [state, setState] = useState<ProfileState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // ProtectedRoute keeps this page behind a signed-in user; a null one only ever means
    // the auth state has not settled, so the page keeps showing its loading state.
    if (user === null) {
      setState({ status: "loading" });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    void loadOrRegisterProfile(
      api,
      { displayName: user.displayName, email: user.email },
      // Newly provisioned claims only exist in a freshly minted ID token.
      async () => {
        await user.getIdToken(true);
      },
    ).then((result) => {
      if (cancelled) {
        return;
      }
      setState(
        result.status === "ready"
          ? { status: "ready", profile: result.profile }
          : { status: "error", message: result.message },
      );
    });
    return () => {
      cancelled = true;
    };
  }, [user, attempt]);

  return { state, reload: () => setAttempt((count) => count + 1) };
}
