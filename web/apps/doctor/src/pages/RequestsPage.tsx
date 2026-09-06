// My Requests: every access request this clinician has raised, grouped by where it got to.
//
// Read-only. A request cannot be cancelled, edited or re-sent — the backend offers no such
// operation, and nothing on this page pretends otherwise. What a doctor may actually read is
// never answered here either: that is decided per read, at the enforcement choke point.
//
// All state lives in useSentRequests; all wording lives in requests/view.ts. This file
// chooses sections and renders.

import { Inbox, Send } from "lucide-react";
import { Link } from "react-router-dom";

import { ErrorState } from "@/components/common/ErrorState";
import { Badge, Button, Card, CardContent } from "@pulseos/ui";

import { SentRequestCard } from "@/requests/components/SentRequestCard";
import { SentRequestsSkeleton } from "@/requests/components/SentRequestsSkeleton";
import { useSentRequests } from "@/requests/useSentRequests";
import { REQUEST_SECTIONS, statusLabel, statusTone, type SentRequestView } from "@/requests/view";

export function RequestsPage() {
  const requests = useSentRequests();

  return (
    <div className="space-y-8">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">My Requests</h2>
        <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
          Every access request you have raised, and where each one got to. The patient decides
          category by category; nothing becomes readable until they approve.
        </p>
      </div>

      {requests.status === "loading" ? (
        <SentRequestsSkeleton />
      ) : requests.status === "error" ? (
        <ErrorState
          title="Could not load your requests."
          message={requests.message ?? "Something went wrong."}
          onRetry={requests.reload}
        />
      ) : requests.total === 0 ? (
        <NoRequests />
      ) : (
        <>
          {REQUEST_SECTIONS.map((section) => (
            <RequestSection
              key={section.bucket}
              heading={statusLabel(section.status)}
              tone={statusTone(section.status)}
              requests={requests.buckets[section.bucket]}
            />
          ))}

          {requests.truncated ? (
            <p className="text-muted-foreground text-xs">
              Showing your {requests.pageSize} most recent requests. Older ones are not listed yet.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

interface RequestSectionProps {
  heading: string;
  tone: ReturnType<typeof statusTone>;
  requests: readonly SentRequestView[];
}

/** A section renders only when it holds something — an account with nothing withdrawn never
 * sees an empty "Withdrawn" heading. */
function RequestSection({ heading, tone, requests }: RequestSectionProps) {
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
      <div className="space-y-4">
        {requests.map((request) => (
          <SentRequestCard key={request.id} request={request} />
        ))}
      </div>
    </section>
  );
}

/** Nothing raised yet — point at the one place a request can be created. */
function NoRequests() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
        <span className="bg-secondary text-muted-foreground flex size-16 items-center justify-center rounded-2xl">
          <Inbox className="size-7" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <p className="text-foreground text-[15px] font-medium">No requests yet</p>
          <p className="text-muted-foreground mx-auto max-w-sm text-sm leading-relaxed">
            Find a patient by their Pulse Health ID to see which kinds of record they hold, then ask
            for the ones you need.
          </p>
        </div>
        <Button asChild variant="outline" size="sm" className="gap-2">
          <Link to="/patients">
            <Send className="size-4" aria-hidden />
            Find a patient
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
