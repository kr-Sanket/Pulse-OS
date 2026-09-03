// Audit History: the append-only trail of every access to the patient's records, a summary
// of the figures behind it, and a standing note on what the log guarantees.
//
// Presentation only — everything comes from src/data/audit.ts and nothing here calls the API
// or holds state. Export Log is visual per spec.

import { Download } from "lucide-react";

import { AuditInfoCard } from "@/components/audit/AuditInfoCard";
import { AuditSummaryCard } from "@/components/audit/AuditSummaryCard";
import { AuditTimelineItem } from "@/components/audit/AuditTimelineItem";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AUDIT_EVENTS } from "@/data/audit";

export function AuditPage() {
  const lastIndex = AUDIT_EVENTS.length - 1;

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">Audit History</h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            Review every access made to your health records.
          </p>
        </div>
        <Button variant="outline" className="gap-2">
          <Download className="size-4" aria-hidden />
          Export Log
        </Button>
      </div>

      <section aria-labelledby="history-heading" className="space-y-4">
        <div className="flex items-center gap-2.5">
          <h3 id="history-heading" className="text-sm font-semibold">
            Recent Access History
          </h3>
          <Badge variant="info">{AUDIT_EVENTS.length}</Badge>
        </div>
        {AUDIT_EVENTS.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No one has accessed your records yet. Every access will appear here.
          </p>
        ) : (
          <ol>
            {AUDIT_EVENTS.map((event, index) => (
              <AuditTimelineItem key={event.id} event={event} isLast={index === lastIndex} />
            ))}
          </ol>
        )}
      </section>

      <section aria-labelledby="summary-heading" className="space-y-4">
        <h3 id="summary-heading" className="text-sm font-semibold">
          Summary
        </h3>
        <AuditSummaryCard />
      </section>

      <AuditInfoCard />
    </div>
  );
}
