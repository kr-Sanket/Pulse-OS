// Dashboard: the patient's Health ID, four figures, what needs their attention, and what
// has happened lately.
//
// Wired to the backend, and the only page that reads from five of them at once. There is no
// aggregate endpoint, so every figure is counted over the page its source returned —
// useDashboard loads each endpoint exactly once and shares it between the widgets that need
// it, and view.ts turns those pages into rows and figures.
//
// Sections fail independently: an audit log that will not load leaves the records, requests,
// grants and Health ID exactly as they are.

import { CalendarClock, IdCard, ShieldQuestion } from "lucide-react";

import { ErrorState } from "@/components/common/ErrorState";
import { ActivityList } from "@/components/dashboard/ActivityList";
import { DashboardWidgetSkeleton } from "@/components/dashboard/DashboardWidgetSkeleton";
import { ExpiringGrantsCard } from "@/components/dashboard/ExpiringGrantsCard";
import { HeroCard } from "@/components/dashboard/HeroCard";
import { QuickActionCard } from "@/components/dashboard/QuickActionCard";
import { ReviewQueueCard } from "@/components/dashboard/ReviewQueueCard";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { StatCard } from "@/components/dashboard/StatCard";
import { StatCardSkeleton } from "@/components/dashboard/StatCardSkeleton";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDashboard } from "@/dashboard/useDashboard";
import { firstNameOf, HERO, QUICK_ACTIONS } from "@/dashboard/view";

export function DashboardPage() {
  const dashboard = useDashboard();
  const { profile, recentRecords, recentActivity, reviewQueue, expiringGrants } = dashboard;
  const patient = profile.status === "ready" ? profile.profile : null;

  return (
    <div className="space-y-8">
      <div className="space-y-2 pt-1">
        <p className="text-muted-foreground text-sm">Good morning,</p>
        {patient === null ? (
          <Skeleton className="h-9 w-48" />
        ) : (
          <h2 className="text-foreground text-3xl font-semibold tracking-tight">
            {firstNameOf(patient.fullName)}
          </h2>
        )}
      </div>

      {profile.status === "loading" ? (
        <HeroSkeleton />
      ) : profile.status === "error" ? (
        <ErrorState
          title="Could not load your profile."
          message={profile.message}
          onRetry={dashboard.reloadProfile}
        />
      ) : (
        <HeroCard
          icon={IdCard}
          title={profile.profile.fullName}
          badgeLabel={HERO.badgeLabel}
          footnote={HERO.footnote}
        >
          <span className="font-mono tracking-tight">{profile.profile.healthId}</span>
        </HeroCard>
      )}

      <section aria-label="Overview">
        <div className="grid grid-cols-2 gap-5 lg:grid-cols-4">
          {dashboard.stats.map((stat) =>
            stat.status === "loading" ? (
              <StatCardSkeleton key={stat.id} />
            ) : (
              <StatCard
                key={stat.id}
                label={stat.label}
                value={stat.value}
                unit={stat.unit}
                note={stat.note}
                tone={stat.status === "unavailable" ? "neutral" : stat.tone}
                icon={stat.icon}
              />
            ),
          )}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 lg:gap-7">
        <div className="space-y-6 lg:col-span-2">
          {recentRecords.status === "error" ? (
            <ErrorState
              title="Could not load your records."
              message={recentRecords.message ?? ""}
              onRetry={recentRecords.reload}
            />
          ) : (
            <ActivityList
              title="Recent records"
              actionLabel="View all"
              actionTo="/records"
              entries={recentRecords.status === "loading" ? undefined : recentRecords.data}
              emptyMessage="No records yet."
            />
          )}

          {recentActivity.status === "error" ? (
            <ErrorState
              title="Could not load your recent activity."
              message={recentActivity.message ?? ""}
              onRetry={recentActivity.reload}
            />
          ) : (
            <ActivityList
              title="Recent activity"
              actionLabel="View log"
              actionTo="/audit"
              entries={recentActivity.status === "loading" ? undefined : recentActivity.data}
              emptyMessage="Nothing has happened yet."
            />
          )}
        </div>

        <div className="space-y-6">
          {reviewQueue.status === "loading" ? (
            <DashboardWidgetSkeleton title="Needs your review" icon={ShieldQuestion} />
          ) : reviewQueue.status === "error" ? (
            <ErrorState
              title="Could not load your requests."
              message={reviewQueue.message ?? ""}
              onRetry={reviewQueue.reload}
            />
          ) : (
            <ReviewQueueCard requests={reviewQueue.data} />
          )}

          {expiringGrants.status === "loading" ? (
            <DashboardWidgetSkeleton title="Expiring soon" icon={CalendarClock} />
          ) : expiringGrants.status === "error" ? (
            <ErrorState
              title="Could not load your grants."
              message={expiringGrants.message ?? ""}
              onRetry={expiringGrants.reload}
            />
          ) : (
            <ExpiringGrantsCard grants={expiringGrants.data} />
          )}
        </div>
      </div>

      <SectionCard
        title="Quick actions"
        contentClassName="grid grid-cols-1 gap-4 pt-1 sm:grid-cols-3"
      >
        {QUICK_ACTIONS.map((action) => (
          <QuickActionCard
            key={action.id}
            title={action.title}
            description={action.description}
            actionLabel={action.actionLabel}
            to={action.to}
            icon={action.icon}
          />
        ))}
      </SectionCard>
    </div>
  );
}

/** Placeholder for the identity hero, in the same gradient surface it fills. */
function HeroSkeleton() {
  return (
    <Card
      className="border-primary/20 from-primary-muted/45 to-card overflow-hidden rounded-2xl bg-gradient-to-br [--card-spacing:--spacing(6)]"
      aria-busy
      role="status"
      aria-label="Loading your Health ID"
    >
      <CardContent className="flex flex-col gap-5 sm:flex-row sm:items-start">
        <Skeleton className="size-14 shrink-0 rounded-2xl" />
        <div className="flex-1 space-y-3">
          <Skeleton className="h-5 w-56 max-w-full" />
          <Skeleton className="h-6 w-64 max-w-full" />
          <Skeleton className="h-3 w-72 max-w-full" />
        </div>
      </CardContent>
    </Card>
  );
}
