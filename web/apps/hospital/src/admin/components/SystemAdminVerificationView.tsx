// Primary view component for the System Admin Hospital Verification interface.
//
// Enforces role-based access in the frontend, displays loading/empty/error/success states,
// presents real server-persisted hospitals with status filtering, and executes hospital verification.

import { useState } from "react";
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Info,
  Loader2,
  RotateCcw,
  Search,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from "@pulseos/ui";
import { HospitalVerificationCard } from "./HospitalVerificationCard";
import type { HospitalVerificationState } from "../useHospitalVerification";
import { FILTER_OPTIONS, type VerificationFilter } from "../view";

export interface SystemAdminVerificationViewProps {
  state: HospitalVerificationState;
}

export function SystemAdminVerificationView({ state }: SystemAdminVerificationViewProps) {
  const [inputHid, setInputHid] = useState("");

  const {
    authLoading,
    isAuthorized,
    userRole,
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
  } = state;

  // 1. Loading state during authorization check
  if (authLoading) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 gap-3 text-center">
          <span className="bg-primary/10 text-primary flex size-12 items-center justify-center rounded-xl animate-pulse">
            <ShieldCheck className="size-6" aria-hidden />
          </span>
          <p className="text-foreground text-sm font-medium">
            Checking administrative permissions…
          </p>
          <p className="text-muted-foreground text-xs">
            Verifying your role against the PulseOS security authority.
          </p>
        </CardContent>
      </Card>
    );
  }

  // 2. Error during role check or unauthorized user
  if (!isAuthorized) {
    return (
      <Card className="border-destructive/30 bg-destructive/5">
        <CardContent className="flex flex-col items-center justify-center py-12 gap-4 text-center max-w-lg mx-auto">
          <span className="bg-destructive/10 text-destructive flex size-14 items-center justify-center rounded-2xl">
            <ShieldAlert className="size-7" aria-hidden />
          </span>
          <div className="space-y-1.5">
            <h3 className="text-foreground text-base font-semibold">
              System Administrator Access Required
            </h3>
            <p className="text-muted-foreground text-sm leading-relaxed" role="alert">
              This interface is strictly restricted to PulseOS System Administrators. Your current
              role{" "}
              <Badge variant="outline" className="font-mono text-xs">
                {userRole ?? "UNAUTHENTICATED"}
              </Badge>{" "}
              is not authorized to review or verify hospital accounts.
            </p>
            {authError ? (
              <p className="text-destructive text-xs pt-2">Authorization error: {authError}</p>
            ) : null}
          </div>
          <p className="text-muted-foreground text-xs border-t pt-3 w-full">
            Security boundary enforced by backend dependency <code>RequireSystemAdmin</code> on{" "}
            <code>GET /api/v1/hospitals</code> and{" "}
            <code>POST /api/v1/hospitals/&#123;hid&#125;/verify</code>.
          </p>
        </CardContent>
      </Card>
    );
  }

  // 3. Authorized System Admin interface
  const totalCount = hospitals.length;
  const pendingCount = hospitals.filter((h) => h.status === "PENDING").length;
  const verifiedCount = hospitals.filter((h) => h.status === "VERIFIED").length;
  const suspendedCount = hospitals.filter((h) => h.status === "SUSPENDED").length;
  const rejectedCount = hospitals.filter((h) => h.status === "REJECTED").length;

  async function handleDirectVerify(e: React.FormEvent) {
    e.preventDefault();
    if (!inputHid.trim() || busyHid) return;

    const result = await verify(inputHid);
    if (result) {
      setInputHid("");
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="text-foreground text-2xl font-semibold tracking-tight">
              Hospital Account Verification
            </h2>
            <Badge variant="default" className="text-xs">
              System Admin
            </Badge>
          </div>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            Review registered care organizations and grant platform verification (ADR-015 step 2).
            Verified hospitals can register clinicians and upload medical records.
          </p>
        </div>
      </div>

      {/* Success Alert */}
      {success ? (
        <div
          role="status"
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-emerald-800 dark:text-emerald-300 flex items-start justify-between gap-3 text-sm animate-in fade-in duration-200"
        >
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="size-5 text-emerald-600 shrink-0" aria-hidden />
            <span>{success}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 text-emerald-700 hover:text-emerald-900 dark:hover:text-emerald-100"
            onClick={dismissAlerts}
            aria-label="Dismiss success message"
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>
      ) : null}

      {/* Error Alert */}
      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-destructive flex items-start justify-between gap-3 text-sm animate-in fade-in duration-200"
        >
          <div className="flex items-center gap-2.5">
            <AlertTriangle className="size-5 shrink-0" aria-hidden />
            <span>{error}</span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 text-destructive hover:bg-destructive/10"
            onClick={dismissAlerts}
            aria-label="Dismiss error message"
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>
      ) : null}

      {/* Direct Verification by HID */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Search className="size-4 text-primary" aria-hidden />
            Verify Directly by Hospital ID (HID)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleDirectVerify} className="flex flex-col sm:flex-row gap-3">
            <div className="flex-1">
              <label htmlFor="hospital-hid-input" className="sr-only">
                Hospital ID (HID)
              </label>
              <Input
                id="hospital-hid-input"
                placeholder="Hospital ID (e.g., HID-0001)"
                value={inputHid}
                onChange={(e) => setInputHid(e.target.value)}
                disabled={Boolean(busyHid)}
                className="font-mono text-sm"
              />
            </div>
            <Button
              type="submit"
              variant="default"
              size="sm"
              className="h-9 text-xs"
              disabled={!inputHid.trim() || Boolean(busyHid)}
            >
              {busyHid === inputHid.trim().toUpperCase() ? (
                <>
                  <Loader2 className="size-3.5 mr-1.5 animate-spin" aria-hidden />
                  Verifying…
                </>
              ) : (
                "Verify Hospital"
              )}
            </Button>
          </form>
          <p className="text-muted-foreground text-xs mt-2">
            Submits <code>POST /api/v1/hospitals/&#123;hid&#125;/verify</code> and refreshes the
            live hospital directory upon success.
          </p>
        </CardContent>
      </Card>

      {/* Directory Section */}
      <div className="space-y-4">
        {/* Filter & Refresh Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1.5">
            {FILTER_OPTIONS.map((opt) => {
              const isSelected = filter === opt.id;
              return (
                <Button
                  key={opt.id}
                  variant={isSelected ? "default" : "outline"}
                  size="sm"
                  className="h-8 text-xs font-medium"
                  onClick={() => setFilter(opt.id as VerificationFilter)}
                  disabled={loadingHospitals}
                >
                  {opt.label}
                  {opt.id === "ALL" && totalCount > 0 ? (
                    <span className="ml-1.5 opacity-80 font-mono">({totalCount})</span>
                  ) : null}
                  {opt.id === "PENDING" && pendingCount > 0 ? (
                    <span className="ml-1.5 opacity-80 font-mono">({pendingCount})</span>
                  ) : null}
                  {opt.id === "VERIFIED" && verifiedCount > 0 ? (
                    <span className="ml-1.5 opacity-80 font-mono">({verifiedCount})</span>
                  ) : null}
                  {opt.id === "SUSPENDED" && suspendedCount > 0 ? (
                    <span className="ml-1.5 opacity-80 font-mono">({suspendedCount})</span>
                  ) : null}
                  {opt.id === "REJECTED" && rejectedCount > 0 ? (
                    <span className="ml-1.5 opacity-80 font-mono">({rejectedCount})</span>
                  ) : null}
                </Button>
              );
            })}
          </div>

          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => void refresh()}
            disabled={loadingHospitals || Boolean(busyHid)}
            aria-label="Refresh hospital list"
          >
            <RotateCcw
              className={`size-3.5 mr-1.5 ${loadingHospitals ? "animate-spin" : ""}`}
              aria-hidden
            />
            Refresh
          </Button>
        </div>

        {/* Load Error State */}
        {loadError ? (
          <div
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-destructive flex items-start justify-between gap-3 text-sm"
          >
            <div className="flex items-center gap-2.5">
              <AlertTriangle className="size-5 shrink-0" aria-hidden />
              <span>{`Failed to load hospitals: ${loadError}`}</span>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => void refresh()}
            >
              Retry
            </Button>
          </div>
        ) : null}

        {/* Loading Indicator */}
        {loadingHospitals && hospitals.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16 gap-3 text-center">
              <Loader2 className="size-8 text-primary animate-spin" aria-hidden />
              <p className="text-foreground text-sm font-medium">Loading hospital directory…</p>
              <p className="text-muted-foreground text-xs">
                Fetching live persisted records from PulseOS.
              </p>
            </CardContent>
          </Card>
        ) : totalCount === 0 ? (
          /* Empty State */
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12 gap-3 text-center">
              <span className="bg-muted text-muted-foreground flex size-12 items-center justify-center rounded-xl">
                <Building2 className="size-6" aria-hidden />
              </span>
              <p className="text-foreground text-sm font-medium">
                {filter === "PENDING"
                  ? "No pending hospitals awaiting verification"
                  : filter === "VERIFIED"
                    ? "No verified hospitals found"
                    : filter === "SUSPENDED"
                      ? "No suspended hospitals found"
                      : filter === "REJECTED"
                        ? "No rejected hospitals found"
                        : "No registered hospitals found"}
              </p>
              <p className="text-muted-foreground text-xs max-w-sm">
                {filter === "PENDING"
                  ? "Care organizations self-registering on PulseOS start in PENDING status and will appear here for review."
                  : "Use the search bar above to verify a hospital by identifier, or refresh to check for new registrations."}
              </p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2 text-xs"
                onClick={() => void refresh()}
              >
                <RotateCcw className="size-3 mr-1.5" aria-hidden />
                Refresh Directory
              </Button>
            </CardContent>
          </Card>
        ) : (
          /* Live Hospital Cards */
          <div className="space-y-3">
            {hospitals.map((hospital) => (
              <HospitalVerificationCard
                key={hospital.hid}
                hospital={hospital}
                busy={busyHid === hospital.hid}
                onVerify={(hid) => void verify(hid)}
                onReject={(hid, reason) => void reject(hid, reason)}
                onSuspend={(hid, reason) => void suspend(hid, reason)}
                onReinstate={(hid, reason) => void reinstate(hid, reason)}
                onFetchAuditLogs={fetchAuditLogs}
              />
            ))}
          </div>
        )}
      </div>

      {/* Architecture & Backend Contract Note */}
      <Card className="bg-muted/30 border-muted">
        <CardContent className="pt-4 pb-4 space-y-2 text-xs text-muted-foreground leading-relaxed">
          <div className="flex items-center gap-2 font-medium text-foreground">
            <Info className="size-4 text-primary shrink-0" aria-hidden />
            <span>Platform Verification Architecture & Backend Contract</span>
          </div>
          <p>
            Under <strong>ADR-015</strong>, hospital onboarding is a two-step lifecycle:
            self-registration produces a <code>PENDING</code> organization, and a System
            Administrator marks it <code>VERIFIED</code>.
          </p>
          <ul className="list-disc pl-5 space-y-1 text-muted-foreground">
            <li>
              <strong>Live Directory:</strong> Backed by <code>GET /api/v1/hospitals</code> with
              optional status filtering (<code>PENDING</code> / <code>VERIFIED</code>), secured by{" "}
              <code>RequireSystemAdmin</code>.
            </li>
            <li>
              <strong>Verification:</strong> Backed by{" "}
              <code>POST /api/v1/hospitals/&#123;hid&#125;/verify</code>, enforced by{" "}
              <code>RequireSystemAdmin</code>.
            </li>
            <li>
              <strong>Lifecycle &amp; Audit (ADR-034):</strong> Rejection (
              <code>POST /api/v1/hospitals/&#123;hid&#125;/reject</code>), suspension (
              <code>POST /api/v1/hospitals/&#123;hid&#125;/suspend</code>), reinstatement (
              <code>POST /api/v1/hospitals/&#123;hid&#125;/reinstate</code>), and audit trail (
              <code>GET /api/v1/hospitals/&#123;hid&#125;/audit-logs</code>) are fully authoritative
              on the server.
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
