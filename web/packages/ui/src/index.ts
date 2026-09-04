// The shared foundation every PulseOS portal builds on (ADR-003: apps stay separate at the
// routing and deploy level but share components, tokens and plumbing).
//
// What lives here is what is genuinely identical across portals: the authentication layer,
// the request-result contract, the load-once hook, and the design tokens. What does not is
// each app's shadcn primitives — those are generated per app by the shadcn CLI into
// `src/components/ui`, which is that tool's own model — and each app's navigation shell,
// which differs by role.
//
// Design tokens are a CSS entry point, not a TS export: `@import "@pulseos/ui/tokens.css"`.

export { authProvider, type AuthProvider, type AuthUser } from "./auth/provider";
export { getFirebaseAuth, isFirebaseConfigured } from "./auth/firebase";
export {
  AuthProvider as AuthContextProvider,
  useAuth,
  type AuthContextValue,
} from "./auth/AuthContext";

export { LoadingScreen } from "./components/LoadingScreen";
export { ProtectedRoute } from "./components/ProtectedRoute";

export { attempt, failure, statusFailure, NETWORK_FAILURE, type ApiResult } from "./lib/apiResult";
export {
  useApiResource,
  type Loader,
  type Resource,
  type ApiResourceState,
} from "./lib/useApiResource";
export {
  formatCalendarDate,
  formatInstantDate,
  formatInstantTime,
  formatRelativeTime,
} from "./lib/dates";
export { formatFileSize } from "./lib/fileSize";
export {
  categoryLabel,
  categoryLabels,
  listCategories,
  type RecordCategory,
} from "./lib/recordCategories";
export { cn } from "./lib/utils";
export { initialsFor } from "./lib/initials";

export const UI_PACKAGE_NAME = "@pulseos/ui";
