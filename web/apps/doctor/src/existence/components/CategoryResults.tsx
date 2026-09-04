// The answer to a search: which categories the patient holds records in.
//
// Every state the results area can be in lives here, so the page stays a layout. The list
// shows category names and nothing else — no counts, no filenames, no hospitals, no dates
// — because that is all the endpoint returns and all a clinician may see before consent.

import { FolderOpen, ShieldQuestion } from "lucide-react";

import { ErrorState } from "@/components/common/ErrorState";
import { IconChip } from "@/components/shell/IconChip";
import { SectionCard } from "@/components/shell/SectionCard";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { SearchOutcome } from "@/existence/view";

export interface CategoryResultsProps {
  outcome: SearchOutcome;
}

const SKELETON_ROWS = ["first", "second", "third"];

export function CategoryResults({ outcome }: CategoryResultsProps) {
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

  return (
    <SectionCard
      title="Available records"
      description={`${outcome.categories.length} kind${
        outcome.categories.length === 1 ? "" : "s"
      } of record exist for this patient. Request access to read any of them.`}
      contentClassName="space-y-3 pt-1"
    >
      <ul className="space-y-3">
        {outcome.categories.map((category) => (
          <li key={category.code} className="flex items-center gap-3.5">
            <IconChip icon={FolderOpen} size="sm" />
            <span className="text-foreground text-sm font-medium">{category.displayName}</span>
          </li>
        ))}
      </ul>
      <p className="text-muted-foreground pt-1 text-xs leading-relaxed">
        Existence only — contents stay sealed until the patient grants access per category.
      </p>
    </SectionCard>
  );
}
