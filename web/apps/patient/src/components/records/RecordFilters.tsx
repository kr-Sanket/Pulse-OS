// Search field and category chips.
//
// The chips are the backend's controlled vocabulary (GET /record-categories) with an "All"
// chip in front; selecting one re-queries the API by category code. The search field is
// client-side over the records already loaded — the API has no search parameter — so it is
// controlled by the page rather than left uncontrolled as it was on mock data.

import { Search } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import type { RecordCategory } from "@/records/api";
import { cn } from "@pulseos/ui";

export interface RecordFiltersProps {
  categories: readonly RecordCategory[];
  /** The selected category code; null is the "All" chip. */
  active: string | null;
  onSelect: (categoryCode: string | null) => void;
  query: string;
  onQueryChange: (query: string) => void;
  /** Chips are still loading. The search field stays usable throughout. */
  loading?: boolean;
}

const SKELETON_CHIPS = ["w-12", "w-24", "w-20", "w-28", "w-16"];

export function RecordFilters({
  categories,
  active,
  onSelect,
  query,
  onQueryChange,
  loading = false,
}: RecordFiltersProps) {
  return (
    <div className="space-y-4">
      <div className="relative">
        <Search
          className="text-muted-foreground pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2"
          aria-hidden
        />
        <input
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search records..."
          aria-label="Search records"
          className="border-input bg-card text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/25 h-11 w-full rounded-xl border pr-4 pl-10 text-sm shadow-sm shadow-black/[0.02] transition-colors duration-150 outline-none focus-visible:ring-[3px]"
        />
      </div>

      {loading ? (
        <div className="flex flex-wrap gap-2" aria-hidden>
          {SKELETON_CHIPS.map((width) => (
            <Skeleton key={width} className={cn("h-7 rounded-full", width)} />
          ))}
        </div>
      ) : (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by category">
          <FilterChip label="All" active={active === null} onSelect={() => onSelect(null)} />
          {categories.map((category) => (
            <FilterChip
              key={category.code}
              label={category.displayName}
              active={category.code === active}
              onSelect={() => onSelect(category.code)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FilterChip({
  label,
  active,
  onSelect,
}: {
  label: string;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onSelect}
      className={cn(
        "rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors duration-150",
        active
          ? "bg-primary-muted text-primary"
          : "border-border/60 text-muted-foreground hover:text-foreground hover:bg-accent border",
      )}
    >
      {label}
    </button>
  );
}
