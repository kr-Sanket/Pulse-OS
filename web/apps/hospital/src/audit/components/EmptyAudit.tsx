// Nothing captured yet.
//
// The wording is load-bearing and is fixed in audit/view.ts: this says no activity has been
// *recorded*, never that no records were accessed. The audit log knows what it captured, and
// several things a hospital does are deliberately outside it (ADR-022) — so a page claiming
// nothing happened would be making a promise the system cannot keep.

import { ScrollText } from "lucide-react";

import { Card, CardContent } from "@pulseos/ui";

import { EMPTY_BODY, EMPTY_TITLE } from "@/audit/view";

export function EmptyAudit() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
        <span className="bg-secondary text-muted-foreground flex size-16 items-center justify-center rounded-2xl">
          <ScrollText className="size-7" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <p className="text-foreground text-[15px] font-medium">{EMPTY_TITLE}</p>
          <p className="text-muted-foreground mx-auto max-w-md text-sm leading-relaxed">
            {EMPTY_BODY}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
