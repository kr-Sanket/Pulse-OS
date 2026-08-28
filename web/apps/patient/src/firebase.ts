// Firebase web SDK bootstrap (modular SDK, ADR-011). Config is env-driven — no
// hardcoded credentials; see .env.example.

import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

function requiredEnv(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(
      `Missing ${name}. Copy web/apps/patient/.env.example to .env.local and fill in ` +
        "your Firebase web app config.",
    );
  }
  return value;
}

const firebaseApp = initializeApp({
  apiKey: requiredEnv("VITE_FIREBASE_API_KEY", import.meta.env.VITE_FIREBASE_API_KEY),
  authDomain: requiredEnv("VITE_FIREBASE_AUTH_DOMAIN", import.meta.env.VITE_FIREBASE_AUTH_DOMAIN),
  projectId: requiredEnv("VITE_FIREBASE_PROJECT_ID", import.meta.env.VITE_FIREBASE_PROJECT_ID),
});

export const firebaseAuth = getAuth(firebaseApp);
