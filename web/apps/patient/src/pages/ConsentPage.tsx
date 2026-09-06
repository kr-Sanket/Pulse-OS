// Consent Requests: the pending queue, the requests already settled, and standing guidance
// about what an approval means.
//
// Wired to the backend: GET /access-requests/inbox for the list, and
// POST /access-requests/{id}/approve | reject for the answers. All of the state, both
// reads and the per-row answers, lives in useConsentInbox; all of the mapping lives in
// consent/view.ts. This file chooses sections and renders.
//
// Answering does not refetch. The API's response says what it recorded, the hook remembers
// it, and the request moves section on the next render — so one failed answer leaves every
// other row untouched.

import { History } from "lucide-react";

import { ErrorState } from "@/components/common/ErrorState";
import { ConsentInboxSkeleton } from "@/components/consent/ConsentInboxSkeleton";
import { ConsentInfoCard } from "@/components/consent/ConsentInfoCard";
import { DecidedConsentCard } from "@/components/consent/DecidedConsentCard";
import { PendingRequestCard } from "@/components/consent/PendingRequestCard";
import { Badge, Button } from "@pulseos/ui";

import { useConsentInbox } from "@/consent/useConsentInbox";
import type { RequestBucket, RequestBuckets } from "@/consent/view";

/** The settled sections, in the order they are shown. Each renders only when it has rows,
 * so an account with nothing declined never sees an empty "Declined" heading. */
const SETTLED_SECTIONS: readonly {
  bucket: RequestBucket;
  heading: string;
  tone: "success" | "destructive" | "neutral" | "info";
}[] = [
  { bucket: "approved", heading: "Approved", tone: "success" },
  { bucket: "rejected", heading: "Declined", tone: "destructive" },
  { bucket: "expired", heading: "Expired", tone: "neutral" },
  { bucket: "decided", heading: "Answered Earlier", tone: "info" },
  { bucket: "withdrawn", heading: "Withdrawn by the Requester", tone: "neutral" },
];

export function ConsentPage() {
  const inbox = useConsentInbox();

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

      {inbox.status === "loading" ? (
        <ConsentInboxSkeleton />
      ) : inbox.status === "error" ? (
        <ErrorState
          title="Could not load your consent requests."
          message={inbox.message ?? "Something went wrong."}
          onRetry={inbox.reload}
        />
      ) : (
        <>
          <section aria-labelledby="pending-heading" className="space-y-4">
            <div className="flex items-center gap-2.5">
              <h3 id="pending-heading" className="text-sm font-semibold">
                Pending Requests
              </h3>
              <Badge variant="warning">{inbox.buckets.pending.length}</Badge>
            </div>
            {inbox.buckets.pending.length === 0 ? (
              <p className="text-muted-foreground text-sm">Nothing waiting on you.</p>
            ) : (
              <div className="space-y-4">
                {inbox.buckets.pending.map((request) => (
                  <PendingRequestCard
                    key={request.id}
                    request={request}
                    busy={inbox.busyOn(request.id)}
                    error={inbox.errorOn(request.id)}
                    onDecide={(kind) => inbox.decide(request.id, request.categoryCodes, kind)}
                  />
                ))}
              </div>
            )}
          </section>

          {SETTLED_SECTIONS.map((section) => (
            <SettledSection
              key={section.bucket}
              heading={section.heading}
              tone={section.tone}
              requests={inbox.buckets[section.bucket]}
            />
          ))}

          {inbox.truncated ? (
            <p className="text-muted-foreground text-xs">
              Showing your most recent requests. Older ones are not listed yet.
            </p>
          ) : null}
        </>
      )}

      <ConsentInfoCard />
    </div>
  );
}

interface SettledSectionProps {
  heading: string;
  tone: "success" | "destructive" | "neutral" | "info";
  requests: RequestBuckets[RequestBucket];
}

function SettledSection({ heading, tone, requests }: SettledSectionProps) {
  if (requests.length === 0) {
    return null;
  }
  const headingId = `${heading.toLowerCase().replace(/\s+/g, "-")}-heading`;
  return (
    <section aria-labelledby={headingId} className="space-y-4">
      <div className="flex items-center gap-2.5">
        <h3 id={headingId} className="text-sm font-semibold">
          {heading}
        </h3>
        <Badge variant={tone}>{requests.length}</Badge>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {requests.map((request) => (
          <DecidedConsentCard key={request.id} request={request} />
        ))}
      </div>
    </section>
  );
}
