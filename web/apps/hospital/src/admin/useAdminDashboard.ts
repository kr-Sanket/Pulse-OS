// State management for the System Admin Dashboard landing page.
//
// Fetches real server-persisted hospitals via listHospitals (GET /api/v1/hospitals),
// computes verification metrics (pending, verified, total), and extracts
// pending organizations requiring administrative review.

import { useCallback, useEffect, useState } from "react";

import { api } from "@/api";
import { listHospitals } from "./api";
import { toReviewItemFromResponse, type HospitalReviewItem } from "./view";
import type { PulseOSClient } from "@pulseos/api-client";

export interface AdminDashboardMetrics {
  totalCount: number;
  pendingCount: number;
  verifiedCount: number;
}

export interface UseAdminDashboardOptions {
  client?: PulseOSClient;
  initialHospitals?: readonly HospitalReviewItem[];
  skipAutoFetch?: boolean;
}

export interface AdminDashboardState {
  loading: boolean;
  error: string | null;
  metrics: AdminDashboardMetrics;
  pendingHospitals: readonly HospitalReviewItem[];
  allHospitals: readonly HospitalReviewItem[];
  refresh: () => Promise<void>;
}

export function computeAdminMetrics(items: readonly HospitalReviewItem[]): AdminDashboardMetrics {
  const totalCount = items.length;
  const pendingCount = items.filter((h) => h.status === "PENDING").length;
  const verifiedCount = items.filter((h) => h.status === "VERIFIED").length;
  return { totalCount, pendingCount, verifiedCount };
}

export function useAdminDashboard(options?: UseAdminDashboardOptions): AdminDashboardState {
  const client = options?.client ?? api;
  const [loading, setLoading] = useState(
    options?.initialHospitals === undefined && !options?.skipAutoFetch,
  );
  const [error, setError] = useState<string | null>(null);
  const [hospitals, setHospitals] = useState<readonly HospitalReviewItem[]>(
    options?.initialHospitals ?? [],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await listHospitals(client);
    if (result.status === "ready") {
      setHospitals(result.data.items.map(toReviewItemFromResponse));
    } else {
      setError(result.message);
    }
    setLoading(false);
  }, [client]);

  useEffect(() => {
    if (options?.skipAutoFetch || options?.initialHospitals !== undefined) {
      return;
    }
    const controller = new AbortController();
    let mounted = true;

    async function load() {
      setLoading(true);
      setError(null);
      const result = await listHospitals(client, { signal: controller.signal });
      if (!mounted) return;
      if (result.status === "ready") {
        setHospitals(result.data.items.map(toReviewItemFromResponse));
      } else {
        setError(result.message);
      }
      setLoading(false);
    }

    void load();
    return () => {
      mounted = false;
      controller.abort();
    };
  }, [client, options?.skipAutoFetch, options?.initialHospitals]);

  const metrics = computeAdminMetrics(hospitals);
  const pendingHospitals = hospitals.filter((h) => h.status === "PENDING");

  return {
    loading,
    error,
    metrics,
    pendingHospitals,
    allHospitals: hospitals,
    refresh,
  };
}
