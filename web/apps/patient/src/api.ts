// The app's single API client instance (ADR-003). ALL backend calls go through this —
// never fetch()/axios. Bearer auth is attached centrally by the client middleware.

import { createPulseOSClient } from "@pulseos/api-client";

import { firebaseAuth } from "./firebase";

export const api = createPulseOSClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  getAccessToken: async () => {
    const user = firebaseAuth.currentUser;
    return user === null ? null : user.getIdToken();
  },
});
