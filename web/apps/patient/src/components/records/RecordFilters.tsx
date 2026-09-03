// Search field and category chips.
//
// Presentation only, per spec: the field is uncontrolled and the chips track which one is
// selected purely so the active state is visible. Neither narrows the list — filtering
// lands with the API slice.

import { Search } from "lucide-react";

import { RECORD_FILTERS, type RecordFilter } from "@/data/records";
import { cn } from "@/lib/utils";

export interface RecordFiltersProps {
  active: RecordFilter;
  onSelect: (filter: RecordFilter) => void;
}

export function RecordFilters({ active, onSelect }: RecordFiltersProps) {
  return (
    <div className="space-y-4">
      <div className="relative">
        <Search
          className="text-muted-foreground pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2"
          aria-hidden
        />
        <input
          type="search"
          placeholder="Search records..."
          aria-label="Search records"
          className="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/25 h-11 w-full rounded-xl border pr-4 pl-10 text-sm shadow-sm shadow-black/[0.02] transition-colors duration-150 outline-none focus-visible:ring-[3px]"
        />
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by category">
        {RECORD_FILTERS.map((filter) => {
          const isActive = filter === active;
          return (
            <button
              key={filter}
              type="button"
              aria-pressed={isActive}
              onClick={() => onSelect(filter)}
              className={cn(
                "rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors duration-150",
                isActive
                  ? "bg-primary-muted text-primary"
                  : "border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent border",
              )}
            >
              {filter}
            </button>
          );
        })}
      </div>
    </div>
  );
}
