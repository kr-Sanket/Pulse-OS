// Medical Records: header, search and filter chips, a list of record cards, and a summary
// panel for the selected record on md and up.
//
// Presentation only — every record comes from src/data/records.ts and nothing here calls
// the API. Local state is limited to which chip looks active and which record the panel is
// showing; both are UI concerns, not data ones.

import { Upload } from "lucide-react";
import { useState } from "react";

import { EmptyRecordsState } from "@/components/records/EmptyRecordsState";
import { RecordCard } from "@/components/records/RecordCard";
import { RecordDetailsPanel } from "@/components/records/RecordDetailsPanel";
import { RecordFilters } from "@/components/records/RecordFilters";
import { Button } from "@/components/ui/button";
import { MEDICAL_RECORDS, type RecordFilter } from "@/data/records";

export function RecordsPage() {
  const [activeFilter, setActiveFilter] = useState<RecordFilter>("All");
  const [selectedId, setSelectedId] = useState<string | undefined>(MEDICAL_RECORDS[0]?.id);

  const selectedRecord =
    MEDICAL_RECORDS.find((record) => record.id === selectedId) ?? MEDICAL_RECORDS[0];
  const hasRecords = MEDICAL_RECORDS.length > 0;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">Medical Records</h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            View and manage all of your health records from connected healthcare providers.
          </p>
        </div>
        <Button className="gap-2">
          <Upload className="size-4" aria-hidden />
          Upload Record
        </Button>
      </div>

      <RecordFilters active={activeFilter} onSelect={setActiveFilter} />

      {hasRecords ? (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3 lg:gap-7">
          <div className="space-y-4 md:col-span-2">
            {MEDICAL_RECORDS.map((record) => (
              <RecordCard
                key={record.id}
                record={record}
                selected={record.id === selectedRecord?.id}
                onSelect={setSelectedId}
              />
            ))}
          </div>

          {/* Summary panel: desktop and tablet only, per spec. */}
          <aside className="hidden md:block" aria-label="Record details">
            {selectedRecord === undefined ? null : <RecordDetailsPanel record={selectedRecord} />}
          </aside>
        </div>
      ) : (
        <EmptyRecordsState />
      )}
    </div>
  );
}
