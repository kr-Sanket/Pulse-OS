// Shown when the timeline has nothing to render, rather than an empty list.
//
// Two situations reach it, and only one of them has a way out: the filter is hiding
// everything there is, or nothing has been recorded at all. The heading and body are the
// same because they are true either way — no one else has touched these records — but the
// button appears only when there is genuinely something to reveal. A button that visibly
// does nothing would teach the reader that the control is broken.

import { ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { NO_EXTERNAL_ACCESS } from "@/audit/view";

export interface AuditEmptyStateProps {
  /** How many of the patient's own events the filter is holding back. */
  hiddenCount: number;
  onShowOwnActivity: () => void;
}

export function AuditEmptyState({ hiddenCount, onShowOwnActivity }: AuditEmptyStateProps) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
        <span className="bg-secondary text-muted-foreground flex size-16 items-center justify-center rounded-2xl">
          <ShieldCheck className="size-7" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <p className="text-foreground text-[15px] font-medium">{NO_EXTERNAL_ACCESS.title}</p>
          <p className="text-muted-foreground mx-auto max-w-sm text-sm leading-relaxed">
            {NO_EXTERNAL_ACCESS.body}
          </p>
        </div>
        {hiddenCount === 0 ? null : (
          <Button variant="outline" size="sm" onClick={onShowOwnActivity}>
            {NO_EXTERNAL_ACCESS.action}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
