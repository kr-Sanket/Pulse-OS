// Consent Requests: the pending queue, previously approved consents, and standing guidance
// about what an approval means.
//
// Presentation only — everything comes from src/data/consents.ts and nothing here calls the
// API or holds state. Approve, Decline, View and History are visual per spec.

import { History } from "lucide-react";

import { ApprovedConsentCard } from "@/components/consent/ApprovedConsentCard";
import { ConsentInfoCard } from "@/components/consent/ConsentInfoCard";
import { PendingRequestCard } from "@/components/consent/PendingRequestCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { APPROVED_CONSENTS, PENDING_REQUESTS } from "@/data/consents";

export function ConsentPage() {
  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">
            Consent Requests
          </h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            Review and manage requests to access your health records.
          </p>
        </div>
        <Button variant="outline" className="gap-2">
          <History className="size-4" aria-hidden />
          History
        </Button>
      </div>

      <section aria-labelledby="pending-heading" className="space-y-4">
        <div className="flex items-center gap-2.5">
          <h3 id="pending-heading" className="text-sm font-semibold">
            Pending Requests
          </h3>
          <Badge variant="warning">{PENDING_REQUESTS.length}</Badge>
        </div>
        {PENDING_REQUESTS.length === 0 ? (
          <p className="text-muted-foreground text-sm">Nothing waiting on you.</p>
        ) : (
          <div className="space-y-4">
            {PENDING_REQUESTS.map((request) => (
              <PendingRequestCard key={request.id} request={request} />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="approved-heading" className="space-y-4">
        <h3 id="approved-heading" className="text-sm font-semibold">
          Previously Approved
        </h3>
        {APPROVED_CONSENTS.length === 0 ? (
          <p className="text-muted-foreground text-sm">You have not approved any requests yet.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {APPROVED_CONSENTS.map((consent) => (
              <ApprovedConsentCard key={consent.id} consent={consent} />
            ))}
          </div>
        )}
      </section>

      <ConsentInfoCard />
    </div>
  );
}
