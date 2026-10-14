// The answer to a search: which categories the patient holds records in, and which of them
// the clinician wants to ask for.
//
// Every state the results area can be in lives here, so the page stays a layout. The list
// shows category names and nothing else — no counts, no filenames, no hospitals, no dates
// — because that is all the endpoint returns and all a clinician may see before consent.
//
// Selection is owned by useAccessRequest and arrives as props: this component reports ticks
// and clicks, and decides nothing about what may be requested.

import { FolderOpen, Send, ShieldQuestion } from "lucide-react";

import { ErrorState } from "@/components/common/ErrorState";
import { IconChip } from "@/components/shell/IconChip";
import { SectionCard } from "@/components/shell/SectionCard";
import { Badge, Button, Card, CardContent, Checkbox, cn, Label, Skeleton } from "@pulseos/ui";

import type { SearchOutcome } from "@/existence/view";

export interface CategorySelection {
  /** Category codes currently ticked. */
  selected: ReadonlySet<string>;
  /** Category codes already granted to the clinician. */
  grantedCodes?: ReadonlySet<string>;
  onToggle: (code: string) => void;
  onClear: () => void;
  onRequestAccess: () => void;
  /** False until at least one category is ticked. */
  canRequest: boolean;
}

export interface CategoryResultsProps {
  outcome: SearchOutcome;
  selection: CategorySelection;
}

const SKELETON_ROWS = ["first", "second", "third"];

export function CategoryResults({ outcome, selection }: CategoryResultsProps) {
  if (outcome.kind === "idle") {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <span className="bg-secondary text-muted-foreground flex size-14 items-center justify-center rounded-2xl">
            <ShieldQuestion className="size-6" aria-hidden />
          </span>
          <p className="text-foreground text-[15px] font-medium">Search for a patient</p>
          <p className="text-muted-foreground max-w-sm text-sm leading-relaxed">
            Enter a Pulse Health ID above to see which kinds of record that patient holds.
          </p>
        </CardContent>
      </Card>
    );
  }

  if (outcome.kind === "searching") {
    return (
      <SectionCard title="Available records" contentClassName="space-y-3 pt-1">
        <div aria-busy role="status" aria-label="Searching" className="space-y-3">
          {SKELETON_ROWS.map((row) => (
            <div key={row} className="flex items-center gap-3.5">
              <Skeleton className="size-9 shrink-0 rounded-lg" />
              <Skeleton className="h-4 w-44 max-w-full" />
            </div>
          ))}
        </div>
      </SectionCard>
    );
  }

  if (outcome.kind === "error") {
    return <ErrorState title="Search could not be completed." message={outcome.message} />;
  }

  if (outcome.kind === "none") {
    return (
      <SectionCard title="Available records" contentClassName="pt-1">
        <div className="flex flex-col items-center gap-3 py-8 text-center">
          <span className="bg-secondary text-muted-foreground flex size-14 items-center justify-center rounded-2xl">
            <FolderOpen className="size-6" aria-hidden />
          </span>
          <p className="text-foreground text-[15px] font-medium">No records on PulseOS yet</p>
          <p className="text-muted-foreground max-w-sm text-sm leading-relaxed">
            <span className="font-mono text-[13px]">{outcome.healthId}</span> is a PulseOS patient,
            but no hospital has added a record for them yet.
          </p>
        </div>
      </SectionCard>
    );
  }

  const chosen = selection.selected.size;

  return (
    <SectionCard
      title="Available records"
      description={`${outcome.categories.length} kind${
        outcome.categories.length === 1 ? "" : "s"
      } of record exist for this patient. Select what you need, then request access.`}
      contentClassName="space-y-4 pt-1"
    >
      <ul className="space-y-1">
        {outcome.categories.map((category) => {
          const isGranted = selection.grantedCodes?.has(category.code) ?? false;
          const inputId = `category-${category.code}`;
          const ticked = !isGranted && selection.selected.has(category.code);
          return (
            <li key={category.code}>
              <Label
                htmlFor={inputId}
                className={cn(
                  "flex items-center gap-3.5 rounded-xl px-2 py-2 font-normal transition-colors duration-150",
                  isGranted
                    ? "cursor-default text-muted-foreground select-none"
                    : "cursor-pointer hover:bg-accent/40",
                )}
              >
                <Checkbox
                  id={inputId}
                  checked={ticked}
                  disabled={isGranted}
                  onCheckedChange={() => {
                    if (!isGranted) {
                      selection.onToggle(category.code);
                    }
                  }}
                />
                <IconChip
                  icon={FolderOpen}
                  size="sm"
                  className={isGranted ? "opacity-60" : undefined}
                />
                <span
                  className={cn(
                    "text-sm font-medium",
                    isGranted ? "text-muted-foreground" : "text-foreground",
                  )}
                >
                  {category.displayName}
                </span>
                {isGranted ? (
                  <Badge variant="success" className="text-xs font-medium gap-1">
                    ✓ Access granted
                  </Badge>
                ) : null}
              </Label>
            </li>
          );
        })}
      </ul>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-muted-foreground text-xs" aria-live="polite">
          {chosen === 0
            ? "Nothing selected yet."
            : `${chosen} of ${outcome.categories.length} selected.`}
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          {chosen === 0 ? null : (
            <Button variant="ghost" size="sm" onClick={selection.onClear}>
              Clear selection
            </Button>
          )}
          <Button
            size="sm"
            className="justify-center gap-2"
            disabled={!selection.canRequest}
            onClick={selection.onRequestAccess}
          >
            <Send className="size-4" aria-hidden />
            Request Access
          </Button>
        </div>
      </div>

      <p className="text-muted-foreground text-xs leading-relaxed">
        Existence only — contents stay sealed until the patient grants access per category.
      </p>
    </SectionCard>
  );
}
