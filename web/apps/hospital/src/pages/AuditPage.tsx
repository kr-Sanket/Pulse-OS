// Audit History: the access activity PulseOS captured for this hospital's staff.
//
// GET /api/v1/hospitals/me/audit-logs, scoped server-side to the caller's own hospital —
// there is no hospital parameter to send and none to get wrong (ADR-023).
//
// Deliberately does **not** load the hospital profile. Two reasons: reading history is not
// an operational action, so a PENDING hospital may do it, and the one thing the profile
// would tell this page (404, no admin profile) is something the audit endpoint already says
// for itself. One request, no gate.
//
// All state lives in useAudit; all wording lives in audit/view.ts.

import { ErrorState } from "@/components/common/ErrorState";
import { AuditEventList } from "@/audit/components/AuditEventList";
import { AuditSkeleton } from "@/audit/components/AuditSkeleton";
import { EmptyAudit } from "@/audit/components/EmptyAudit";
import { useAudit } from "@/audit/useAudit";
import { PAGE_DESCRIPTION, SCOPE_NOTE } from "@/audit/view";
import { Button } from "@pulseos/ui";

export function AuditPage() {
  const audit = useAudit();

  return (
    <div className="space-y-8">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">Audit History</h2>
        <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
          {PAGE_DESCRIPTION}
        </p>
        <p className="text-muted-foreground max-w-2xl text-xs leading-relaxed">{SCOPE_NOTE}</p>
      </div>

      {audit.isLoading ? (
        <AuditSkeleton />
      ) : audit.error !== null && audit.items.length === 0 ? (
        <ErrorState
          title="Could not load your audit history."
          message={audit.error}
          onRetry={audit.retry}
        />
      ) : audit.items.length === 0 ? (
        <EmptyAudit />
      ) : (
        <div className="space-y-4">
          <AuditEventList events={audit.items} />

          {/* A failure *after* the first page keeps what is already on screen: the rows
              loaded so far are still true, and replacing them with an error would discard
              a compliance view over a transient problem. */}
          {audit.error === null ? null : (
            <p role="alert" className="text-destructive text-sm leading-relaxed">
              {audit.error}
            </p>
          )}

          {audit.hasMore || audit.isLoadingMore ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                size="sm"
                disabled={audit.isLoadingMore}
                onClick={audit.loadMore}
              >
                {audit.isLoadingMore ? "Loading…" : "Load more"}
              </Button>
            </div>
          ) : (
            <p className="text-muted-foreground text-center text-xs">
              You have reached the end of the recorded history.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
