// Renders a hospital account within the System Admin verification queue.
//
// Shows identifier, name, address, current verification status, lifecycle action controls,
// confirmation modal with optional reason, and lifecycle audit history (ADR-034).

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Ban,
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  History,
  Loader2,
  RotateCcw,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  formatInstantDate,
  Textarea,
} from "@pulseos/ui";
import { StatusBadge } from "@/components/shell/StatusBadge";
import type { HospitalAuditLog } from "../api";
import {
  formatVerifierId,
  historyPanelState,
  LIFECYCLE_ACTION_CONFIG,
  VERIFICATION_STATUS_CONFIG,
  type HospitalReviewItem,
} from "../view";

export interface HospitalVerificationCardProps {
  hospital: HospitalReviewItem;
  busy: boolean;
  onVerify: (hid: string) => void;
  onReject?: (hid: string, reason?: string) => void;
  onSuspend?: (hid: string, reason?: string) => void;
  onReinstate?: (hid: string, reason?: string) => void;
  onFetchAuditLogs?: (hid: string) => Promise<readonly HospitalAuditLog[]>;
}

type DialogAction = "REJECT" | "SUSPEND" | "REINSTATE" | null;

export function HospitalVerificationCard({
  hospital,
  busy,
  onVerify,
  onReject,
  onSuspend,
  onReinstate,
  onFetchAuditLogs,
}: HospitalVerificationCardProps) {
  const [dialogAction, setDialogAction] = useState<DialogAction>(null);
  const [reasonInput, setReasonInput] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [auditLogs, setAuditLogs] = useState<readonly HospitalAuditLog[] | null>(null);

  const statusConfig = VERIFICATION_STATUS_CONFIG[hospital.status] ?? {
    label: hospital.status,
    tone: "neutral",
  };

  const handleOpenDialog = (action: DialogAction) => {
    setDialogAction(action);
    setReasonInput("");
  };

  const handleCloseDialog = () => {
    setDialogAction(null);
    setReasonInput("");
  };

  const handleConfirmAction = () => {
    const trimmedReason = reasonInput.trim() || undefined;
    if (dialogAction === "REJECT" && onReject) {
      onReject(hospital.hid, trimmedReason);
    } else if (dialogAction === "SUSPEND" && onSuspend) {
      onSuspend(hospital.hid, trimmedReason);
    } else if (dialogAction === "REINSTATE" && onReinstate) {
      onReinstate(hospital.hid, trimmedReason);
    }
    handleCloseDialog();
  };

  const loadHistory = useCallback(async () => {
    if (!onFetchAuditLogs) return;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      setAuditLogs(await onFetchAuditLogs(hospital.hid));
    } catch (err) {
      // Leave auditLogs null so the next open retries instead of caching the failure.
      setHistoryError(err instanceof Error ? err.message : "Could not load history.");
    } finally {
      setHistoryLoading(false);
    }
  }, [hospital.hid, onFetchAuditLogs]);

  // A lifecycle action changes the status and appends an event: drop the cached trail, and
  // reload it if the panel is open, so the history never lags the badge above it.
  const [historyStatus, setHistoryStatus] = useState(hospital.status);
  useEffect(() => {
    if (historyStatus === hospital.status) return;
    setHistoryStatus(hospital.status);
    setAuditLogs(null);
    if (showHistory) void loadHistory();
  }, [hospital.status, historyStatus, showHistory, loadHistory]);

  const handleToggleHistory = () => {
    const nextShow = !showHistory;
    setShowHistory(nextShow);
    if (nextShow && auditLogs === null) void loadHistory();
  };

  const panelState = historyPanelState(historyLoading, historyError, auditLogs);

  const isReasonTooLong = reasonInput.length > 255;

  return (
    <Card className="transition-shadow duration-150 hover:shadow-md hover:shadow-black/[0.04]">
      <CardContent className="space-y-4 pt-5 pb-5">
        {/* Top Header Row */}
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="bg-primary/10 text-primary flex size-10 shrink-0 items-center justify-center rounded-lg mt-0.5">
              <Building2 className="size-5" aria-hidden />
            </span>
            <div className="space-y-1 min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-foreground text-[15px] font-semibold">{hospital.name}</h3>
                <Badge variant="outline" className="font-mono text-xs font-normal">
                  {hospital.hid}
                </Badge>
              </div>
              <p className="text-muted-foreground text-xs leading-relaxed truncate">
                {hospital.address ?? "Address not recorded"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 self-start sm:self-auto">
            <StatusBadge tone={statusConfig.tone}>{statusConfig.label}</StatusBadge>
          </div>
        </div>

        {/* State Description Banner */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2 border-t text-xs">
          <div className="text-muted-foreground flex items-start gap-1.5 min-w-0">
            {hospital.status === "VERIFIED" && (
              <div className="space-y-0.5 min-w-0">
                <div className="flex items-center gap-1.5">
                  <CheckCircle2
                    className="size-3.5 text-emerald-600 dark:text-emerald-400 shrink-0"
                    aria-hidden
                  />
                  <span>Verified: Organization can register doctors and upload records.</span>
                </div>
                {hospital.verifiedAt || hospital.verifiedByUserId ? (
                  <p className="text-muted-foreground/80 pl-5 text-[11px]">
                    Verified
                    {hospital.verifiedAt ? ` on ${formatInstantDate(hospital.verifiedAt)}` : ""}
                    {hospital.verifiedByUserId
                      ? ` by Admin (${formatVerifierId(hospital.verifiedByUserId)})`
                      : ""}
                  </p>
                ) : null}
              </div>
            )}

            {hospital.status === "PENDING" && (
              <div className="flex items-center gap-1.5">
                <Clock
                  className="size-3.5 text-amber-600 dark:text-amber-400 shrink-0"
                  aria-hidden
                />
                <span>
                  Awaiting verification: Doctors and record uploads are currently blocked.
                </span>
              </div>
            )}

            {hospital.status === "SUSPENDED" && (
              <div className="flex items-center gap-1.5 text-amber-700 dark:text-amber-400">
                <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
                <span>
                  Suspended: Doctor activation and clinical operations are temporarily suspended.
                </span>
              </div>
            )}

            {hospital.status === "REJECTED" && (
              <div className="flex items-center gap-1.5 text-destructive">
                <XCircle className="size-3.5 shrink-0" aria-hidden />
                <span>
                  Registration rejected: Application has been permanently rejected (terminal state).
                </span>
              </div>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2 shrink-0">
            {hospital.status === "PENDING" && (
              <>
                <Button
                  variant="default"
                  size="sm"
                  className="h-8 text-xs font-medium"
                  disabled={busy}
                  onClick={() => onVerify(hospital.hid)}
                  aria-label={`Verify hospital ${hospital.name}`}
                >
                  <ShieldCheck className="size-3.5 mr-1" aria-hidden />
                  {busy ? "Verifying…" : "Verify Hospital"}
                </Button>
                {onReject && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-xs font-medium text-destructive hover:bg-destructive/10"
                    disabled={busy}
                    onClick={() => handleOpenDialog("REJECT")}
                    aria-label={`Reject hospital ${hospital.name}`}
                  >
                    <Ban className="size-3.5 mr-1" aria-hidden />
                    Reject
                  </Button>
                )}
              </>
            )}

            {hospital.status === "VERIFIED" && onSuspend && (
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs font-medium text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/20"
                disabled={busy}
                onClick={() => handleOpenDialog("SUSPEND")}
                aria-label={`Suspend hospital ${hospital.name}`}
              >
                <AlertTriangle className="size-3.5 mr-1" aria-hidden />
                Suspend
              </Button>
            )}

            {hospital.status === "SUSPENDED" && onReinstate && (
              <Button
                variant="default"
                size="sm"
                className="h-8 text-xs font-medium"
                disabled={busy}
                onClick={() => handleOpenDialog("REINSTATE")}
                aria-label={`Reinstate hospital ${hospital.name}`}
              >
                <RotateCcw className="size-3.5 mr-1" aria-hidden />
                Reinstate
              </Button>
            )}

            {hospital.status === "REJECTED" && (
              <Badge variant="outline" className="font-mono text-xs text-muted-foreground">
                Terminal State
              </Badge>
            )}
          </div>
        </div>

        {/* History Toggle Bar */}
        <div className="flex items-center justify-between pt-1 text-xs">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={handleToggleHistory}
            aria-expanded={showHistory}
          >
            <History className="size-3.5 mr-1.5" aria-hidden />
            {showHistory ? "Hide Audit History" : "View Audit History"}
            {showHistory ? (
              <ChevronUp className="size-3.5 ml-1" aria-hidden />
            ) : (
              <ChevronDown className="size-3.5 ml-1" aria-hidden />
            )}
          </Button>
        </div>

        {/* Collapsible History Section */}
        {showHistory && (
          <div className="border rounded-md p-3 bg-muted/20 space-y-2.5 text-xs animate-in fade-in duration-150">
            <h4 className="font-semibold text-foreground flex items-center justify-between">
              <span>Lifecycle Audit Trail</span>
              {historyLoading && (
                <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
              )}
            </h4>

            {panelState === "loading" && (
              <p className="text-muted-foreground py-2 flex items-center gap-2">
                <Loader2 className="size-3.5 animate-spin" />
                Loading lifecycle audit history…
              </p>
            )}

            {panelState === "error" && (
              <p role="alert" className="text-destructive py-2">{`Error: ${historyError}`}</p>
            )}

            {panelState === "empty" && (
              <p className="text-muted-foreground py-1">No lifecycle audit events recorded.</p>
            )}

            {panelState === "list" && auditLogs && (
              <div className="divide-y divide-border/60">
                {auditLogs.map((log) => {
                  const actionMeta = LIFECYCLE_ACTION_CONFIG[log.action] ?? {
                    label: log.action,
                    tone: "neutral",
                  };
                  return (
                    <div key={log.id} className="py-2 first:pt-0 last:pb-0 space-y-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <StatusBadge tone={actionMeta.tone}>{actionMeta.label}</StatusBadge>
                          <span className="text-muted-foreground font-mono text-[11px]">
                            by Admin ({formatVerifierId(log.actorUserId)})
                          </span>
                        </div>
                        <span className="text-muted-foreground text-[11px]">
                          {formatInstantDate(log.occurredAt)}
                        </span>
                      </div>
                      {log.reason ? (
                        <p className="text-foreground/90 pl-1 text-[11px] italic bg-background/50 rounded p-1 border">
                          &ldquo;{log.reason}&rdquo;
                        </p>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Confirmation Modal for Reject / Suspend / Reinstate */}
        <Dialog open={dialogAction !== null} onOpenChange={(open) => !open && handleCloseDialog()}>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>
                {dialogAction === "REJECT" && "Reject Hospital Registration"}
                {dialogAction === "SUSPEND" && "Suspend Hospital Organization"}
                {dialogAction === "REINSTATE" && "Reinstate Hospital Organization"}
              </DialogTitle>
              <DialogDescription>
                {dialogAction === "REJECT" &&
                  `Are you sure you want to reject ${hospital.name} (${hospital.hid})? Rejection is a permanent, terminal action.`}
                {dialogAction === "SUSPEND" &&
                  `Suspend ${hospital.name} (${hospital.hid})? Suspended organizations cannot activate doctors or upload medical records.`}
                {dialogAction === "REINSTATE" &&
                  `Reinstate ${hospital.name} (${hospital.hid}) to active VERIFIED status?`}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-2 py-2">
              <label
                htmlFor={`reason-${hospital.hid}`}
                className="text-xs font-medium text-foreground flex justify-between"
              >
                <span>Reason (Optional)</span>
                <span
                  className={`text-[11px] ${isReasonTooLong ? "text-destructive" : "text-muted-foreground"}`}
                >
                  {reasonInput.length}/255
                </span>
              </label>
              <Textarea
                id={`reason-${hospital.hid}`}
                placeholder={
                  dialogAction === "REJECT"
                    ? "Enter reason for rejection (e.g., Incomplete regulatory license)…"
                    : dialogAction === "SUSPEND"
                      ? "Enter reason for suspension (e.g., Pending compliance audit)…"
                      : "Enter reason for reinstatement (e.g., Annual compliance cleared)…"
                }
                value={reasonInput}
                onChange={(e) => setReasonInput(e.target.value)}
                maxLength={300}
                rows={3}
                className="text-xs resize-none"
              />
              {isReasonTooLong && (
                <p className="text-destructive text-[11px]">
                  Reason must not exceed 255 characters.
                </p>
              )}
            </div>

            <DialogFooter className="gap-2 sm:gap-0">
              <Button variant="outline" size="sm" onClick={handleCloseDialog} disabled={busy}>
                Cancel
              </Button>
              <Button
                variant={dialogAction === "REJECT" ? "destructive" : "default"}
                size="sm"
                onClick={handleConfirmAction}
                disabled={busy || isReasonTooLong}
              >
                {busy
                  ? "Processing…"
                  : `Confirm ${dialogAction === "REJECT" ? "Rejection" : dialogAction === "SUSPEND" ? "Suspension" : "Reinstatement"}`}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}
