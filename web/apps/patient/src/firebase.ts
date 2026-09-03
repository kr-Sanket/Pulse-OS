// Firebase web SDK bootstrap (modular SDK, ADR-011). Config is env-driven — no
// hardcoded credentials; see .env.example.
//
// Initialization is lazy and memoized rather than performed at module load, so that
// importing this module is side-effect free. That lets the auth layer decide whether
// Firebase should be used at all (see auth/provider.ts) without initializing it. The
// missing-config error itself is unchanged: whoever asks for the auth instance without
// configuration still gets it, and in production the auth layer asks immediately at
// startup — so a misconfigured production build still fails loudly and at the same point.

import { initializeApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";

function requiredEnv(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(
      `Missing ${name}. Copy web/apps/patient/.env.example to .env.local and fill in ` +
        "your Firebase web app config.",
    );
  }
  return value;
}

/** True when every Firebase variable the app needs is present. */
export function isFirebaseConfigured(): boolean {
  return Boolean(
    import.meta.env.VITE_FIREBASE_API_KEY &&
    import.meta.env.VITE_FIREBASE_AUTH_DOMAIN &&
    import.meta.env.VITE_FIREBASE_PROJECT_ID,
  );
}

let auth: Auth | null = null;

/** The Firebase Auth instance, initializing the app on first use.
 *  Throws if configuration is missing. */
export function getFirebaseAuth(): Auth {
  if (auth === null) {
    const app = initializeApp({
      apiKey: requiredEnv("VITE_FIREBASE_API_KEY", import.meta.env.VITE_FIREBASE_API_KEY),
      authDomain: requiredEnv(
        "VITE_FIREBASE_AUTH_DOMAIN",
        import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
      ),
      projectId: requiredEnv("VITE_FIREBASE_PROJECT_ID", import.meta.env.VITE_FIREBASE_PROJECT_ID),
    });
    auth = getAuth(app);
  }
  return auth;
}
