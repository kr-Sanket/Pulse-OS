// The one authentication interface every PulseOS portal consumes.
//
// Everything above this file — AuthContext, pages, layout, the API client — talks to
// `authProvider` and never to Firebase. Which implementation backs it is decided here,
// exactly once, at module load. Shared by every portal (ADR-003: one auth plumbing, not
// three); each app supplies its own VITE_FIREBASE_* values:
//
//   • Firebase, whenever it is configured, and ALWAYS in a production build.
//   • A development mock, only when `import.meta.env.DEV` is true AND no Firebase
//     configuration is present — so UI work needs no Firebase project.
//
// The production path is constructed eagerly below, which means a production build with
// missing configuration still throws the same "Missing VITE_FIREBASE_API_KEY…" error at
// startup that it did before this abstraction existed.

import { isFirebaseConfigured } from "./firebase";
import { createDevMockAuthProvider } from "./devMockAuthProvider";
import { createFirebaseAuthProvider } from "./firebaseAuthProvider";

/** The subset of an authenticated identity the application actually uses. */
export interface AuthUser {
  uid: string;
  displayName: string | null;
  email: string | null;
  photoURL: string | null;
  /** Bearer token for API calls; `forceRefresh` picks up newly provisioned claims. */
  getIdToken(forceRefresh?: boolean): Promise<string>;
}

export interface AuthProvider {
  /** Which implementation is in use — for diagnostics only; no code branches on it. */
  readonly mode: "firebase" | "development-mock";
  /** Observe sign-in state. Calls the listener with the current value, then on change. */
  subscribe(listener: (user: AuthUser | null) => void): () => void;
  /** The signed-in user right now, for callers outside React (the API client). */
  getCurrentUser(): AuthUser | null;
  signIn(): Promise<void>;
  signOut(): Promise<void>;
}

function selectAuthProvider(): AuthProvider {
  if (import.meta.env.DEV && !isFirebaseConfigured()) {
    return createDevMockAuthProvider();
  }
  return createFirebaseAuthProvider();
}

export const authProvider: AuthProvider = selectAuthProvider();
