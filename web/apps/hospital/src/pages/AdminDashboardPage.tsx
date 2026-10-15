// Dedicated landing page for the PulseOS System Admin dashboard.
//
// Displays real-time metrics derived from persisted hospital records (pending, verified, total),
// highlights pending hospitals needing review, and provides a direct entry point
// into the Hospital Verification queue.

import { ArrowRight, Building2, Clock, RotateCcw, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@pulseos/ui";

import { ErrorState } from "@/components/common/ErrorState";
import { StatusBadge } from "@/components/shell/StatusBadge";
import { useAdminDashboard, type AdminDashboardState } from "@/admin/useAdminDashboard";
import { VERIFICATION_STATUS_CONFIG } from "@/admin/view";

export interface AdminDashboardPageProps {
  state?: AdminDashboardState;
}

export function AdminDashboardPage({ state: injectedState }: AdminDashboardPageProps) {
  const defaultState = useAdminDashboard();
  const state = injectedState ?? defaultState;

  const { loading, error, metrics, pendingHospitals, allHospitals, refresh } = state;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pt-1">
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
            Platform Administration
          </p>
          <h2 className="text-foreground text-3xl font-semibold tracking-tight">
            System Admin Dashboard
          </h2>
          <p className="text-muted-foreground text-sm">
            Overview of care organizations, onboarding states, and operational verifications.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => void refresh()}
            disabled={loading}
          >
            <RotateCcw className="size-3.5" aria-hidden />
            Refresh Data
          </Button>
          <Link to="/admin/verification">
            <Button size="sm" className="gap-2">
              <ShieldCheck className="size-4" aria-hidden />
              Verification Queue
            </Button>
          </Link>
        </div>
      </div>

      {/* Error state */}
      {error !== null ? (
        <ErrorState
          title="Could not load platform metrics."
          message={error}
          onRetry={() => void refresh()}
        />
      ) : loading ? (
        <div className="space-y-8">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Skeleton className="h-32 rounded-2xl" />
            <Skeleton className="h-32 rounded-2xl" />
            <Skeleton className="h-32 rounded-2xl" />
          </div>
          <Skeleton className="h-28 rounded-2xl" />
          <Skeleton className="h-64 rounded-2xl" />
        </div>
      ) : (
        <>
          {/* Metrics Grid */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {/* 1. Pending Verification */}
            <Card
              className={
                metrics.pendingCount > 0 ? "border-amber-500/40 bg-amber-500/5 shadow-xs" : ""
              }
            >
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <p className="text-muted-foreground text-sm font-medium">Pending Verification</p>
                  <span className="bg-amber-500/10 text-amber-600 dark:text-amber-400 flex size-9 items-center justify-center rounded-xl">
                    <Clock className="size-5" aria-hidden />
                  </span>
                </div>
                <div className="mt-4">
                  <span className="text-foreground text-3xl font-bold tracking-tight">
                    {metrics.pendingCount}
                  </span>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {metrics.pendingCount === 1
                      ? "1 hospital awaiting review"
                      : `${metrics.pendingCount} hospitals awaiting review`}
                  </p>
                </div>
              </CardContent>
            </Card>

            {/* 2. Verified Hospitals */}
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <p className="text-muted-foreground text-sm font-medium">Verified Hospitals</p>
                  <span className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex size-9 items-center justify-center rounded-xl">
                    <ShieldCheck className="size-5" aria-hidden />
                  </span>
                </div>
                <div className="mt-4">
                  <span className="text-foreground text-3xl font-bold tracking-tight">
                    {metrics.verifiedCount}
                  </span>
                  <p className="text-muted-foreground mt-1 text-xs">
                    Active & operational organizations
                  </p>
                </div>
              </CardContent>
            </Card>

            {/* 3. Total Registered */}
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <p className="text-muted-foreground text-sm font-medium">Total Registered</p>
                  <span className="bg-primary/10 text-primary flex size-9 items-center justify-center rounded-xl">
                    <Building2 className="size-5" aria-hidden />
                  </span>
                </div>
                <div className="mt-4">
                  <span className="text-foreground text-3xl font-bold tracking-tight">
                    {metrics.totalCount}
                  </span>
                  <p className="text-muted-foreground mt-1 text-xs">
                    Total care organizations on PulseOS
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Quick Action / Review Queue Banner */}
          <Card className="border-primary/20 bg-primary/5">
            <CardContent className="flex flex-col sm:flex-row sm:items-center sm:justify-between p-6 gap-4">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="text-primary size-5" aria-hidden />
                  <h3 className="text-foreground text-base font-semibold">
                    Hospital Verification Queue
                  </h3>
                </div>
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {metrics.pendingCount > 0
                    ? `There ${metrics.pendingCount === 1 ? "is 1 hospital" : `are ${metrics.pendingCount} hospitals`} awaiting identity verification and operational approval.`
                    : "All registered hospital organizations are currently verified. No pending reviews."}
                </p>
              </div>
              <Link to="/admin/verification">
                <Button className="shrink-0 gap-2">
                  Open Verification Queue
                  <ArrowRight className="size-4" aria-hidden />
                </Button>
              </Link>
            </CardContent>
          </Card>

          {/* Pending Reviews Section */}
          {pendingHospitals.length > 0 ? (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Clock className="text-amber-500 size-4" aria-hidden />
                  Awaiting Administrative Review ({pendingHospitals.length})
                </CardTitle>
                <CardDescription>
                  These hospitals have registered but cannot operate until verified by a System
                  Administrator.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="divide-border divide-y">
                  {pendingHospitals.map((hospital) => (
                    <div
                      key={hospital.hid}
                      className="flex flex-col sm:flex-row sm:items-center sm:justify-between py-3.5 gap-2"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-foreground text-sm font-semibold truncate">
                            {hospital.name}
                          </p>
                          <span className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded text-muted-foreground">
                            {hospital.hid}
                          </span>
                        </div>
                        <p className="text-muted-foreground text-xs truncate mt-0.5">
                          {hospital.address ?? "No address recorded"}
                        </p>
                      </div>
                      <Link to="/admin/verification">
                        <Button variant="outline" size="sm" className="gap-1.5 text-xs">
                          Review in Queue
                          <ArrowRight className="size-3.5" aria-hidden />
                        </Button>
                      </Link>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ) : null}

          {/* Directory of Hospitals */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Building2 className="text-primary size-4" aria-hidden />
                Registered Organizations Directory ({allHospitals.length})
              </CardTitle>
              <CardDescription>
                Server-authoritative records of all care organizations on the PulseOS network.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              {allHospitals.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-10 text-center gap-3">
                  <Building2 className="text-muted-foreground size-8" aria-hidden />
                  <p className="text-foreground text-sm font-medium">No hospitals registered yet</p>
                  <p className="text-muted-foreground text-xs max-w-sm">
                    When a hospital registers through the onboarding portal, it will appear here for
                    administrative verification.
                  </p>
                </div>
              ) : (
                <div className="divide-border divide-y">
                  {allHospitals.map((hospital) => {
                    const statusConfig = VERIFICATION_STATUS_CONFIG[hospital.status];
                    return (
                      <div
                        key={hospital.hid}
                        className="flex flex-col sm:flex-row sm:items-center sm:justify-between py-3.5 gap-2"
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-foreground text-sm font-semibold truncate">
                              {hospital.name}
                            </p>
                            <span className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded text-muted-foreground">
                              {hospital.hid}
                            </span>
                          </div>
                          <p className="text-muted-foreground text-xs truncate mt-0.5">
                            {hospital.address ?? "No address recorded"}
                          </p>
                        </div>
                        <div className="flex items-center gap-3 shrink-0">
                          <StatusBadge tone={statusConfig.tone}>{statusConfig.label}</StatusBadge>
                          {hospital.status === "PENDING" ? (
                            <Link to="/admin/verification">
                              <Button size="sm" variant="outline" className="text-xs">
                                Verify
                              </Button>
                            </Link>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
