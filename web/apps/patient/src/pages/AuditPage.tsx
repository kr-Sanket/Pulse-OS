// Audit History: the append-only trail of every access to the patient's records, a summary
// of the events shown, and a standing note on what the log guarantees.
//
// Wired to the backend: GET /audit-logs. All state lives in useAudit; all mapping — the
// action vocabulary, who acted, which rows the default view shows, the summary figures —
// lives in audit/view.ts. This file chooses sections and renders; it filters nothing.
//
// The page opens on other people's activity, because "who else used my records?" is the
// question it exists to answer and a patient's own reads bury it. One switch restores the
// whole trail. Nothing is removed from the log by either view.
//
// Export Log is presentational: there is no export endpoint.

import { Download } from "lucide-react";

import { AuditActivityToggle } from "@/components/audit/AuditActivityToggle";
import { AuditEmptyState } from "@/components/audit/AuditEmptyState";
import { AuditInfoCard } from "@/components/audit/AuditInfoCard";
import { AuditSummaryCard } from "@/components/audit/AuditSummaryCard";
import { AuditTimelineItem } from "@/components/audit/AuditTimelineItem";
import { AuditTimelineSkeleton } from "@/components/audit/AuditTimelineSkeleton";
import { ErrorState } from "@/components/common/ErrorState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAudit } from "@/audit/useAudit";

export function AuditPage() {
  const trail = useAudit();
  const lastIndex = trail.events.length - 1;

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">Audit History</h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            See who else has accessed your health records, and when.
          </p>
        </div>
        <Button variant="outline" className="gap-2">
          <Download className="size-4" aria-hidden />
          Export Log
        </Button>
      </div>

      {trail.status === "loading" ? (
        <AuditTimelineSkeleton />
      ) : trail.status === "error" ? (
        <ErrorState
          title="Could not load your audit history."
          message={trail.message ?? "Something went wrong."}
          onRetry={trail.reload}
        />
      ) : (
        <>
          <AuditActivityToggle
            checked={trail.showOwnActivity}
            onCheckedChange={trail.setShowOwnActivity}
            hiddenCount={trail.hiddenOwnActivity}
          />

          <section aria-labelledby="history-heading" className="space-y-4">
            <div className="flex items-center gap-2.5">
              <h3 id="history-heading" className="text-sm font-semibold">
                Recent Access History
              </h3>
              <Badge variant="info">{trail.events.length}</Badge>
            </div>
            {trail.events.length === 0 ? (
              <AuditEmptyState
                hiddenCount={trail.hiddenOwnActivity}
                onShowOwnActivity={() => trail.setShowOwnActivity(true)}
              />
            ) : (
              <ol>
                {trail.events.map((event, index) => (
                  <AuditTimelineItem key={event.id} event={event} isLast={index === lastIndex} />
                ))}
              </ol>
            )}
            {trail.truncated ? (
              <p className="text-muted-foreground text-xs">
                Showing the {trail.pageSize} most recent events. Older ones are not listed yet.
              </p>
            ) : null}
          </section>

          <section aria-labelledby="summary-heading" className="space-y-4">
            <h3 id="summary-heading" className="text-sm font-semibold">
              Summary of the Events Shown
            </h3>
            <AuditSummaryCard summary={trail.summary} />
          </section>
        </>
      )}

      <AuditInfoCard />
    </div>
  );
}
