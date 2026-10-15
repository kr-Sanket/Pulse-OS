// One pending access request, spacious enough to answer the four questions a patient needs
// before deciding: who is asking, why, what they would see, and by when it lapses.
//
// Presentational: the page owns the request state and the in-flight answer, this renders
// them and allows the patient to approve or decline each requested record category
// individually before submitting their combined decisions.

import { useState } from "react";
import { Building2, Check, CheckCheck, RotateCcw, X, XCircle } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/dashboard/IconChip";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Badge, Button, Card, CardContent, Separator } from "@pulseos/ui";

import type { DecisionKind } from "@/consent/api";
import type { PartialDecisionState, PerCategoryDecisions } from "@/consent/useConsentInbox";
import type { ConsentRequestView } from "@/consent/view";

export interface PendingRequestCardProps {
  request: ConsentRequestView;
  /** Which answer is in flight for this request, if any. */
  busy?: boolean | DecisionKind | null;
  /** Why the last answer to this request failed, if it did. */
  error: string | null;
  onDecide: (decisions: PerCategoryDecisions) => void;
  /** Partial decision state if a previous submission partially succeeded. */
  partial?: PartialDecisionState | null;
}

export function PendingRequestCard({
  request,
  busy,
  error,
  onDecide,
  partial,
}: PendingRequestCardProps) {
  const answering = Boolean(busy);
  const [decisions, setDecisions] = useState<Record<string, "approve" | "reject">>({});

  const alreadyApprovedSet = new Set(partial?.approvedCodes ?? []);
  const remainingCodes = request.categoryCodes.filter((code) => !alreadyApprovedSet.has(code));

  const totalCategories = request.categoryCodes.length;
  const approvedCodes = [
    ...(partial?.approvedCodes ?? []),
    ...remainingCodes.filter((code) => decisions[code] === "approve"),
  ];
  const rejectedCodes = remainingCodes.filter((code) => decisions[code] === "reject");

  const decidedRemainingCount = remainingCodes.filter(
    (code) => decisions[code] !== undefined,
  ).length;
  const decidedCount = Object.keys(decisions).length;
  const allDecided = remainingCodes.length === 0 || decidedRemainingCount === remainingCodes.length;
  const canSubmit = allDecided && remainingCodes.length > 0 && !answering;

  function handleSelect(code: string, choice: "approve" | "reject") {
    if (answering || alreadyApprovedSet.has(code)) return;
    setDecisions((prev) => ({
      ...prev,
      [code]: choice,
    }));
  }

  function handleSelectAll(choice: "approve" | "reject") {
    if (answering) return;
    const next: Record<string, "approve" | "reject"> = { ...decisions };
    for (const code of remainingCodes) {
      next[code] = choice;
    }
    setDecisions(next);
  }

  function handleClear() {
    if (answering) return;
    setDecisions({});
  }

  function handleSubmit() {
    if (!canSubmit) return;
    onDecide({
      approvedCodes,
      rejectedCodes,
    });
  }

  let submitLabel = "Select a decision for each category";
  if (answering) {
    submitLabel = "Submitting decisions…";
  } else if (partial && partial.approvedCodes.length > 0) {
    submitLabel = allDecided
      ? "Submit Decision for Remaining Categories"
      : "Select decision for remaining categories";
  } else if (allDecided) {
    if (approvedCodes.length === totalCategories) {
      submitLabel = "Approve All";
    } else if (rejectedCodes.length === totalCategories) {
      submitLabel = "Decline All";
    } else {
      submitLabel = `Approve (${approvedCodes.length}) & Decline (${rejectedCodes.length})`;
    }
  }

  return (
    <Card className="transition-shadow duration-150 hover:shadow-md hover:shadow-black/[0.04]">
      <CardContent className="space-y-5">
        <div className="flex items-start gap-4">
          <IconChip icon={Building2} />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground text-[15px] font-medium">{request.hospital}</h3>
            <p className="text-muted-foreground truncate text-sm">{request.clinician}</p>
          </div>
          <StatusBadge tone={request.statusTone}>{request.statusLabel}</StatusBadge>
        </div>

        <Separator />

        <dl className="grid gap-5 sm:grid-cols-2">
          <Detail label="Purpose">{request.purpose}</Detail>
          <Detail label="Request expires">{request.expiresOn}</Detail>
          <Detail label="Requested">{request.requestedAgo}</Detail>
        </dl>

        <Separator />

        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 className="text-foreground text-sm font-semibold">
                Requested Record Categories ({totalCategories})
              </h4>
              <p className="text-muted-foreground text-xs">
                Select Approve or Decline for each category before submitting.
              </p>
            </div>
            <div className="flex items-center gap-1.5">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-xs text-muted-foreground hover:text-foreground"
                disabled={answering}
                onClick={() => handleSelectAll("approve")}
              >
                <CheckCheck className="size-3.5 mr-1" aria-hidden />
                Approve all
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-xs text-muted-foreground hover:text-foreground"
                disabled={answering}
                onClick={() => handleSelectAll("reject")}
              >
                <XCircle className="size-3.5 mr-1" aria-hidden />
                Decline all
              </Button>
              {decidedCount > 0 ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs text-muted-foreground hover:text-foreground"
                  disabled={answering}
                  onClick={handleClear}
                >
                  <RotateCcw className="size-3 mr-1" aria-hidden />
                  Clear
                </Button>
              ) : null}
            </div>
          </div>

          {partial && partial.approvedCodes.length > 0 ? (
            <div
              role="alert"
              className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-300 space-y-1"
            >
              <p className="font-semibold">Partial Decision Notice</p>
              <p>
                Approved categories may already have access granted on the server. Please select a
                decision for the remaining categories to complete your response.
              </p>
            </div>
          ) : null}

          <div className="space-y-2">
            {request.categoryCodes.map((code, index) => {
              const label = request.categories[index] ?? code;
              const isAlreadyGranted = alreadyApprovedSet.has(code);
              const decision = isAlreadyGranted ? "approve" : decisions[code];

              return (
                <div
                  key={code}
                  className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 rounded-md border p-3 bg-muted/20"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-foreground">{label}</span>
                    <Badge variant="outline" className="text-[11px] font-mono font-normal">
                      {code}
                    </Badge>
                    {isAlreadyGranted ? (
                      <Badge variant="success" className="text-[11px]">
                        Access Granted
                      </Badge>
                    ) : null}
                  </div>

                  {isAlreadyGranted ? (
                    <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 font-medium">
                      <Check className="size-3.5" aria-hidden />
                      Approved on Server
                    </div>
                  ) : (
                    <div
                      role="group"
                      aria-label={`Decision for ${label}`}
                      className="flex items-center gap-2"
                    >
                      <Button
                        type="button"
                        size="sm"
                        variant={decision === "approve" ? "default" : "outline"}
                        className={`h-8 gap-1.5 text-xs px-3 ${
                          decision === "approve"
                            ? "bg-emerald-600 hover:bg-emerald-700 text-white border-transparent"
                            : ""
                        }`}
                        disabled={answering}
                        aria-pressed={decision === "approve"}
                        onClick={() => handleSelect(code, "approve")}
                      >
                        <Check className="size-3.5" aria-hidden />
                        Approve
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant={decision === "reject" ? "destructive" : "outline"}
                        className="h-8 gap-1.5 text-xs px-3"
                        disabled={answering}
                        aria-pressed={decision === "reject"}
                        onClick={() => handleSelect(code, "reject")}
                      >
                        <X className="size-3.5" aria-hidden />
                        Decline
                      </Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <p className="text-muted-foreground text-xs leading-relaxed">
            Approved categories grant temporary read access until the request expires. Declined
            categories remain private and cannot be viewed.
          </p>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row pt-2">
          <Button
            size="sm"
            className="justify-center gap-2 sm:w-auto"
            disabled={!canSubmit}
            onClick={handleSubmit}
          >
            <Check className="size-4" aria-hidden />
            {submitLabel}
          </Button>
        </div>

        {error === null ? null : (
          <p role="alert" className="text-destructive text-sm leading-relaxed">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
