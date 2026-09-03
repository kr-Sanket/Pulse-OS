// The summary figures above the trail. Renders StatCard directly rather than wrapping the
// figures in another card — nesting cards would fight the design language everywhere else.
//
// The figures are computed over the loaded page (audit/view.ts): the API exposes no
// aggregate endpoint, and each card's note says which events it counted.

import { StatCard } from "@/components/dashboard/StatCard";
import type { SummaryStat } from "@/audit/view";

export interface AuditSummaryCardProps {
  summary: readonly SummaryStat[];
}

export function AuditSummaryCard({ summary }: AuditSummaryCardProps) {
  return (
    <div className="grid grid-cols-2 gap-5 lg:grid-cols-4">
      {summary.map((stat) => (
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
