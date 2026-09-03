// Development-only stand-in for Firebase Auth.
//
// Selected by auth/provider.ts only when the build is a dev build AND no Firebase
// configuration is present. It signs a fixed user in immediately so the portal opens
// straight onto the dashboard: no Google popup, no Firebase project, no network.
//
// Its token is deliberately not a real credential. Screens that call the backend (the
// profile page) will therefore fail their request and show their error state — that is
// expected in this mode, and is why the mock never engages once Firebase is configured.

import type { AuthProvider, AuthUser } from "./provider";

const MOCK_USER: AuthUser = {
  uid: "dev-user",
  displayName: "Sanket Kumar",
  email: "sanket@example.com",
  photoURL: null,
  getIdToken: () => Promise.resolve("dev-mock-token"),
};

export function createDevMockAuthProvider(): AuthProvider {
  console.warn(
    "[PulseOS] No Firebase config found in a dev build — using the mock auth user " +
      `"${MOCK_USER.displayName}". Add VITE_FIREBASE_* to .env.local to use real auth.`,
  );

  let current: AuthUser | null = MOCK_USER;
  const listeners = new Set<(user: AuthUser | null) => void>();

  const emit = () => {
    for (const listener of listeners) {
      listener(current);
    }
  };

  return {
    mode: "development-mock",
    subscribe: (listener) => {
      listeners.add(listener);
      listener(current); // resolve immediately: nothing to restore from
      return () => {
        listeners.delete(listener);
      };
    },
    getCurrentUser: () => current,
    // Sign-out and sign-in still work, so the guarded-route flow stays exercisable.
    signIn: () => {
      current = MOCK_USER;
      emit();
      return Promise.resolve();
    },
    signOut: () => {
      current = null;
      emit();
      return Promise.resolve();
    },
  };
}
