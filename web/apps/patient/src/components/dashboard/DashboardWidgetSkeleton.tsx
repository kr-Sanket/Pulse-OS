// Placeholder for one of the dashboard's side panels while its source loads. Uses the same
// SectionCard header as the real widget, so only the rows change when the data lands.

import type { LucideIcon } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";

import { SectionCard } from "./SectionCard";

export interface DashboardWidgetSkeletonProps {
  title: string;
  icon: LucideIcon;
  rows?: number;
}

export function DashboardWidgetSkeleton({ title, icon, rows = 2 }: DashboardWidgetSkeletonProps) {
  return (
    <SectionCard title={title} icon={icon} contentClassName="space-y-4 pt-1">
      <div className="space-y-4" aria-busy role="status" aria-label={`Loading ${title}`}>
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="flex items-start gap-3.5">
            <Skeleton className="size-9 shrink-0 rounded-lg" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}
