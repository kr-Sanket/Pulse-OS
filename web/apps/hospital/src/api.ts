// The app's single API client instance (ADR-003). ALL backend calls go through this —
// never fetch()/axios. Bearer auth is attached centrally by the client middleware.
//
// The token comes from the shared auth provider, not from Firebase directly, so this
// module is unaffected by which implementation is in use.
//
// Nothing imports this yet: the shell makes no requests. It exists now so that the first
// feature slice adds a `<feature>/api.ts` beside it rather than a second client.

import { createPulseOSClient } from "@pulseos/api-client";
import { authProvider } from "@pulseos/ui";

export const api = createPulseOSClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  getAccessToken: async () => {
    const user = authProvider.getCurrentUser();
    return user === null ? null : user.getIdToken();
  },
});
