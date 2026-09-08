// Search field, sort control, category chips, and a reset.
//
// Every control here is a query parameter: the chips are the backend's controlled
// vocabulary (GET /record-categories), and search and sort go to the API too. None of them
// filters in the browser — the page holds one page of records at a time, so anything
// decided here could only ever see a slice of the patient's history.
//
// Presentational: it renders the current query and reports changes. The page owns the
// state, the debounce and the cursor reset.

import { ArrowDownWideNarrow, Search, X } from "lucide-react";

import type { RecordCategory, RecordSort } from "@/records/api";
import { SORT_OPTIONS } from "@/records/view";
import { Button, cn, Skeleton } from "@pulseos/ui";

export interface RecordFiltersProps {
  categories: readonly RecordCategory[];
  /** The selected category code; null is the "All" chip. */
  active: string | null;
  onSelect: (categoryCode: string | null) => void;
  query: string;
  onQueryChange: (query: string) => void;
  sort: RecordSort;
  onSortChange: (sort: RecordSort) => void;
  /** Whether "Clear filters" would change anything; the control is hidden when it would not. */
  canClear: boolean;
  onClear: () => void;
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
  sort,
  onSortChange,
  canClear,
  onClear,
  loading = false,
}: RecordFiltersProps) {
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
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

        <div className="relative">
          <ArrowDownWideNarrow
            className="text-muted-foreground pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2"
            aria-hidden
          />
          {/* A native select: two options, and it is keyboard- and screen-reader-correct
              without any of the listbox wiring a custom control would need. */}
          <select
            value={sort}
            onChange={(event) => onSortChange(event.target.value as RecordSort)}
            aria-label="Sort records"
            className="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/25 h-11 w-full cursor-pointer appearance-none rounded-xl border pr-4 pl-10 text-sm shadow-sm shadow-black/[0.02] transition-colors duration-150 outline-none focus-visible:ring-[3px] sm:w-auto"
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="flex flex-wrap gap-2" aria-hidden>
          {SKELETON_CHIPS.map((width) => (
            <Skeleton key={width} className={cn("h-7 rounded-full", width)} />
          ))}
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
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
          {canClear ? (
            <Button variant="ghost" size="sm" className="gap-1.5" onClick={onClear}>
              <X className="size-3.5" aria-hidden />
              Clear filters
            </Button>
          ) : null}
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
