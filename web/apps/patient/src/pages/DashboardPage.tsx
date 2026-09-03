// Dashboard: the visual design migrated from the v0 reference, composed from the existing
// PulseOS dashboard components. Layout only — every value comes from src/data/dashboard.ts
// and nothing here calls the API.
//
// Structure mirrors the reference: greeting, AI summary hero, a four-up figure row, a
// two-thirds/one-third split (recent records beside the review queue and expiring grants),
// then a full-width actions panel.

import { Sparkles } from "lucide-react";

import { ActivityList } from "@/components/dashboard/ActivityList";
import { ExpiringGrantsCard } from "@/components/dashboard/ExpiringGrantsCard";
import { HeroCard } from "@/components/dashboard/HeroCard";
import { QuickActionCard } from "@/components/dashboard/QuickActionCard";
import { ReviewQueueCard } from "@/components/dashboard/ReviewQueueCard";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { StatCard } from "@/components/dashboard/StatCard";
import { useAuth } from "@/auth/AuthContext";
import {
  AI_SUMMARY,
  DASHBOARD_VITALS,
  EXPIRING_GRANTS,
  GREETING_FALLBACK_NAME,
  QUICK_ACTIONS,
  RECENT_RECORDS,
  REVIEW_REQUESTS,
} from "@/data/dashboard";

/** First word of the signed-in user's display name, or a neutral fallback. */
function useFirstName(): string {
  const { user } = useAuth();
  const [first] = (user?.displayName ?? "").trim().split(/\s+/);
  return first !== undefined && first.length > 0 ? first : GREETING_FALLBACK_NAME;
}

export function DashboardPage() {
  const firstName = useFirstName();

  return (
    <div className="space-y-8">
      <div className="space-y-2 pt-1">
        <p className="text-muted-foreground text-sm">Good morning,</p>
        <h2 className="text-foreground text-3xl font-semibold tracking-tight">{firstName}</h2>
      </div>

      <HeroCard
        icon={Sparkles}
        title={AI_SUMMARY.title}
        badgeLabel={AI_SUMMARY.badgeLabel}
        footnote={AI_SUMMARY.footnote}
      >
        {AI_SUMMARY.body}
      </HeroCard>

      <section aria-label="Overview">
        <div className="grid grid-cols-2 gap-5 lg:grid-cols-4">
          {DASHBOARD_VITALS.map((item) => (
            <StatCard
              key={item.id}
              label={item.label}
              value={item.value}
              unit={item.unit}
              note={item.note}
              tone={item.tone}
            />
          ))}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3 lg:gap-7">
        <div className="lg:col-span-2">
          <ActivityList
            title="Recent records"
            actionLabel="View all"
            actionTo="/records"
            entries={RECENT_RECORDS}
            emptyMessage="No records yet."
          />
        </div>

        <div className="space-y-6">
          <ReviewQueueCard requests={REVIEW_REQUESTS} />
          <ExpiringGrantsCard grants={EXPIRING_GRANTS} />
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
