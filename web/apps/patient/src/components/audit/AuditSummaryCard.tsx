// The summary figures above the trail. Renders StatCard directly rather than wrapping the
// figures in another card — nesting cards would fight the design language everywhere else.

import { StatCard } from "@/components/dashboard/StatCard";
import { AUDIT_SUMMARY } from "@/data/audit";

export function AuditSummaryCard() {
  return (
    <div className="grid grid-cols-2 gap-5 lg:grid-cols-4">
      {AUDIT_SUMMARY.map((stat) => (
        <StatCard
          key={stat.id}
          label={stat.label}
          value={stat.value}
          unit={stat.unit}
          note={stat.note}
          tone={stat.tone}
          icon={stat.icon}
        />
      ))}
    </div>
  );
}
