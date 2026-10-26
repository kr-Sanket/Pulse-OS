// State management for the System Admin Hospital Verification interface.
//
// Enforces role-based authorization in the frontend, fetches real server-persisted hospitals,
// supports filtering by verification status, prevents duplicate in-flight submissions,
// and refreshes real data after successful verification.

import { useCallback, useEffect, useState } from "react";

import { api } from "@/api";
import {
  fetchCurrentUser,
  fetchHospitalAuditLogs,
  listHospitals,
  reinstateHospital,
  rejectHospital,
  suspendHospital,
  verifyHospital,
  type Hospital,
  type HospitalAuditLog,
} from "./api";
import {
  toReviewItemFromResponse,
  validateHospitalId,
  type HospitalReviewItem,
  type VerificationFilter,
} from "./view";

export interface UseHospitalVerificationOptions {
  /** Optional initial review queue (e.g. for testing without network). */
  initialQueue?: readonly HospitalReviewItem[];
  /** Optional initial filter. */
  initialFilter?: VerificationFilter;
  /** Optional override for user role (e.g. for testing without auth API call). */
  mockRole?: string | null;
  /** Disable automatic fetch on mount (e.g. for testing). */
  skipAutoFetch?: boolean;
}

export interface HospitalVerificationState {
  /** Authorization check state */
  authLoading: boolean;
  userRole: string | null;
  isAuthorized: boolean;
  authError: string | null;

  /** Queue state */
  loadingHospitals: boolean;
  loadError: string | null;
  hospitals: readonly HospitalReviewItem[];
  filter: VerificationFilter;
  busyHid: string | null;
  error: string | null;
  success: string | null;

  /** Actions */
  verify: (hid: string) => Promise<Hospital | null>;
  reject: (hid: string, reason?: string) => Promise<Hospital | null>;
  suspend: (hid: string, reason?: string) => Promise<Hospital | null>;
  reinstate: (hid: string, reason?: string) => Promise<Hospital | null>;
  /** Rejects with the user-facing message when the history cannot be loaded. */
  fetchAuditLogs: (hid: string) => Promise<readonly HospitalAuditLog[]>;
  refresh: () => Promise<void>;
  setFilter: (filter: VerificationFilter) => void;
  dismissAlerts: () => void;
}

export function useHospitalVerification(
  options?: UseHospitalVerificationOptions,
): HospitalVerificationState {
  const [authLoading, setAuthLoading] = useState(options?.mockRole === undefined);
  const [userRole, setUserRole] = useState<string | null>(options?.mockRole ?? null);
  const [authError, setAuthError] = useState<string | null>(null);

  const [filter, setFilter] = useState<VerificationFilter>(options?.initialFilter ?? "ALL");
  const [loadingHospitals, setLoadingHospitals] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [hospitals, setHospitals] = useState<readonly HospitalReviewItem[]>(
    options?.initialQueue ?? [],
  );

  const [busyHid, setBusyHid] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // 1. Authorize: Check current user role against SYSTEM_ADMIN
  useEffect(() => {
    if (options?.mockRole !== undefined) {
      return;
    }
    const controller = new AbortController();
    let mounted = true;

    async function checkRole() {
      setAuthLoading(true);
      setAuthError(null);
      const result = await fetchCurrentUser(api, controller.signal);
      if (!mounted) return;
      if (result.status === "ready") {
        setUserRole(result.data.role);
      } else {
        setAuthError(result.message);
      }
      setAuthLoading(false);
    }

    void checkRole();
    return () => {
      mounted = false;
      controller.abort();
    };
  }, [options?.mockRole]);

  const isAuthorized = userRole === "SYSTEM_ADMIN";

  // 2. Fetch real server hospitals whenever authorized or filter changes
  const refresh = useCallback(async () => {
    setLoadingHospitals(true);
    setLoadError(null);
    const statusParam = filter === "ALL" ? undefined : filter;
    const result = await listHospitals(api, { status: statusParam });
    if (result.status === "ready") {
      setHospitals(result.data.items.map(toReviewItemFromResponse));
    } else {
      setLoadError(result.message);
    }
    setLoadingHospitals(false);
  }, [filter]);

  useEffect(() => {
    if (!isAuthorized || options?.skipAutoFetch) {
      return;
    }
    const controller = new AbortController();
    let mounted = true;

    async function load() {
      setLoadingHospitals(true);
      setLoadError(null);
      const statusParam = filter === "ALL" ? undefined : filter;
      const result = await listHospitals(api, { status: statusParam, signal: controller.signal });
      if (!mounted) return;
      if (result.status === "ready") {
        setHospitals(result.data.items.map(toReviewItemFromResponse));
      } else {
        setLoadError(result.message);
      }
      setLoadingHospitals(false);
    }

    void load();
    return () => {
      mounted = false;
      controller.abort();
    };
  }, [isAuthorized, filter, options?.skipAutoFetch]);

  // 3. Action: Verify hospital by HID
  const verify = useCallback(
    async (rawHid: string): Promise<Hospital | null> => {
      const hid = rawHid.trim().toUpperCase();

      // Duplicate submission guard
      if (busyHid !== null) {
        return null;
      }

      // Format validation
      const validationError = validateHospitalId(hid);
      if (validationError) {
        setError(validationError);
        setSuccess(null);
        return null;
      }

      setBusyHid(hid);
      setError(null);
      setSuccess(null);

      try {
        const result = await verifyHospital(api, hid);
        if (result.status === "error") {
          setError(result.message);
          return null;
        }

        const verifiedHospital = result.data;
        const updatedItem = toReviewItemFromResponse(verifiedHospital);

        // Immediate optimistic update for responsive UI
        setHospitals((current) => {
          const index = current.findIndex((h) => h.hid === hid);
          if (index >= 0) {
            const next = [...current];
            next[index] = updatedItem;
            return next;
          }
          return [updatedItem, ...current];
        });

        setSuccess(
          `Hospital "${verifiedHospital.name}" (${verifiedHospital.hid}) has been successfully verified.`,
        );

        // Re-sync server-authoritative state
        void refresh();

        return verifiedHospital;
      } finally {
        setBusyHid(null);
      }
    },
    [busyHid, refresh],
  );

  // 4. Action: Reject hospital by HID with optional reason
  const reject = useCallback(
    async (rawHid: string, reason?: string): Promise<Hospital | null> => {
      const hid = rawHid.trim().toUpperCase();
      if (busyHid !== null) return null;

      const validationError = validateHospitalId(hid);
      if (validationError) {
        setError(validationError);
        setSuccess(null);
        return null;
      }

      setBusyHid(hid);
      setError(null);
      setSuccess(null);

      try {
        const result = await rejectHospital(api, hid, reason);
        if (result.status === "error") {
          setError(result.message);
          return null;
        }

        const rejectedHospital = result.data;
        const updatedItem = toReviewItemFromResponse(rejectedHospital);

        setHospitals((current) => {
          const index = current.findIndex((h) => h.hid === hid);
          if (index >= 0) {
            const next = [...current];
            next[index] = updatedItem;
            return next;
          }
          return [updatedItem, ...current];
        });

        setSuccess(
          `Hospital "${rejectedHospital.name}" (${rejectedHospital.hid}) has been rejected.`,
        );
        void refresh();
        return rejectedHospital;
      } finally {
        setBusyHid(null);
      }
    },
    [busyHid, refresh],
  );

  // 5. Action: Suspend hospital by HID with optional reason
  const suspend = useCallback(
    async (rawHid: string, reason?: string): Promise<Hospital | null> => {
      const hid = rawHid.trim().toUpperCase();
      if (busyHid !== null) return null;

      const validationError = validateHospitalId(hid);
      if (validationError) {
        setError(validationError);
        setSuccess(null);
        return null;
      }

      setBusyHid(hid);
      setError(null);
      setSuccess(null);

      try {
        const result = await suspendHospital(api, hid, reason);
        if (result.status === "error") {
          setError(result.message);
          return null;
        }

        const suspendedHospital = result.data;
        const updatedItem = toReviewItemFromResponse(suspendedHospital);

        setHospitals((current) => {
          const index = current.findIndex((h) => h.hid === hid);
          if (index >= 0) {
            const next = [...current];
            next[index] = updatedItem;
            return next;
          }
          return [updatedItem, ...current];
        });

        setSuccess(
          `Hospital "${suspendedHospital.name}" (${suspendedHospital.hid}) has been suspended.`,
        );
        void refresh();
        return suspendedHospital;
      } finally {
        setBusyHid(null);
      }
    },
    [busyHid, refresh],
  );

  // 6. Action: Reinstate hospital by HID with optional reason
  const reinstate = useCallback(
    async (rawHid: string, reason?: string): Promise<Hospital | null> => {
      const hid = rawHid.trim().toUpperCase();
      if (busyHid !== null) return null;

      const validationError = validateHospitalId(hid);
      if (validationError) {
        setError(validationError);
        setSuccess(null);
        return null;
      }

      setBusyHid(hid);
      setError(null);
      setSuccess(null);

      try {
        const result = await reinstateHospital(api, hid, reason);
        if (result.status === "error") {
          setError(result.message);
          return null;
        }

        const reinstatedHospital = result.data;
        const updatedItem = toReviewItemFromResponse(reinstatedHospital);

        setHospitals((current) => {
          const index = current.findIndex((h) => h.hid === hid);
          if (index >= 0) {
            const next = [...current];
            next[index] = updatedItem;
            return next;
          }
          return [updatedItem, ...current];
        });

        setSuccess(
          `Hospital "${reinstatedHospital.name}" (${reinstatedHospital.hid}) has been reinstated.`,
        );
        void refresh();
        return reinstatedHospital;
      } finally {
        setBusyHid(null);
      }
    },
    [busyHid, refresh],
  );

  // 7. Action: Fetch lifecycle audit logs
  const fetchAuditLogs = useCallback(
    async (rawHid: string): Promise<readonly HospitalAuditLog[]> => {
      const hid = rawHid.trim().toUpperCase();
      const result = await fetchHospitalAuditLogs(api, hid);
      if (result.status === "ready") {
        return result.data.items;
      }
      // Surfaced by the history panel itself; an empty list would read as "no events".
      throw new Error(result.message);
    },
    [],
  );

  const dismissAlerts = useCallback(() => {
    setError(null);
    setSuccess(null);
  }, []);

  return {
    authLoading,
    userRole,
    isAuthorized,
    authError,
    loadingHospitals,
    loadError,
    hospitals,
    filter,
    busyHid,
    error,
    success,
    verify,
    reject,
    suspend,
    reinstate,
    fetchAuditLogs,
    refresh,
    setFilter,
    dismissAlerts,
  };
}
