// Active Grants: who currently has access to the patient's records, which grants are close
// to lapsing, what has been withdrawn or has expired, and a standing reminder that access
// is revocable.
//
// Wired to the backend: GET /consent-grants for the listing and
// POST /consent-grants/{id}/revoke for withdrawals. All state lives in useGrants; all
// grouping and mapping lives in grants/view.ts. This file chooses sections and renders.
//
// The API returns one grant per category and the page shows one card per approval, so a
// card's Revoke button withdraws several grants at once — see the revoke flow in useGrants.
// Export is presentational: there is no export endpoint.

import { Download } from "lucide-react";

import { ErrorState } from "@/components/common/ErrorState";
import { ActiveGrantCard } from "@/components/grants/ActiveGrantCard";
import { GrantSummaryCard } from "@/components/grants/GrantSummaryCard";
import { GrantsSkeleton } from "@/components/grants/GrantsSkeleton";
import { PrivacyReminderCard } from "@/components/grants/PrivacyReminderCard";
import { Badge, Button } from "@pulseos/ui";

import { useGrants } from "@/grants/useGrants";
import { EXPIRING_SOON_DAYS, type GrantGroupView } from "@/grants/view";

export function GrantsPage() {
  const grants = useGrants();
  const { active, expiringSoon, revoked, expired } = grants.buckets;

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">Active Grants</h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            Manage hospitals and healthcare providers that currently have access to your medical
            records.
          </p>
        </div>
        <Button variant="outline" className="gap-2">
          <Download className="size-4" aria-hidden />
          Export
        </Button>
      </div>

      {grants.status === "loading" ? (
        <GrantsSkeleton />
      ) : grants.status === "error" ? (
        <ErrorState
          title="Could not load your active grants."
          message={grants.message ?? "Something went wrong."}
          onRetry={grants.reload}
        />
      ) : (
        <>
          <section aria-labelledby="active-heading" className="space-y-4">
            <div className="flex items-center gap-2.5">
              <h3 id="active-heading" className="text-sm font-semibold">
                Currently Active Grants
              </h3>
              <Badge variant="success">{active.length}</Badge>
            </div>
            {active.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No provider currently has access to your records.
              </p>
            ) : (
              <div className="space-y-4">
                {active.map((grant) => (
                  <ActiveGrantCard
                    key={grant.id}
                    grant={grant}
                    busy={grants.busyOn(grant.id)}
                    error={grants.errorOn(grant.id)}
                    onRevoke={() => grants.revoke(grant)}
                  />
                ))}
              </div>
            )}
          </section>

          {/* A filtered view of the list above — the same cards, not copies of them. */}
          <section aria-labelledby="expiring-heading" className="space-y-4">
            <div className="flex items-center gap-2.5">
              <h3 id="expiring-heading" className="text-sm font-semibold">
                Expiring Soon
              </h3>
              <Badge variant="warning">{expiringSoon.length}</Badge>
            </div>
            {expiringSoon.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No grants lapse within the next {EXPIRING_SOON_DAYS} days.
              </p>
            ) : (
              <SummaryGrid grants={expiringSoon} badgeLabel="Expiring" badgeTone="warning" />
            )}
          </section>

          {revoked.length === 0 ? null : (
            <section aria-labelledby="revoked-heading" className="space-y-4">
              <div className="flex items-center gap-2.5">
                <h3 id="revoked-heading" className="text-sm font-semibold">
                  Withdrawn
                </h3>
                <Badge variant="destructive">{revoked.length}</Badge>
              </div>
              <SummaryGrid grants={revoked} />
            </section>
          )}

          {expired.length === 0 ? null : (
            <section aria-labelledby="expired-heading" className="space-y-4">
              <div className="flex items-center gap-2.5">
                <h3 id="expired-heading" className="text-sm font-semibold">
                  Expired
                </h3>
                <Badge variant="neutral">{expired.length}</Badge>
              </div>
              <SummaryGrid grants={expired} />
            </section>
          )}

          {grants.truncated ? (
            <p className="text-muted-foreground text-xs">
              Showing your most recent grants. Older ones are not listed yet.
            </p>
          ) : null}
        </>
      )}

      <PrivacyReminderCard />
    </div>
  );
}

interface SummaryGridProps {
  grants: readonly GrantGroupView[];
  badgeLabel?: string;
  badgeTone?: "warning";
}

function SummaryGrid({ grants, badgeLabel, badgeTone }: SummaryGridProps) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {grants.map((grant) => (
        <GrantSummaryCard
          key={grant.id}
          grant={grant}
          badgeLabel={badgeLabel}
          badgeTone={badgeTone}
        />
      ))}
    </div>
  );
}
