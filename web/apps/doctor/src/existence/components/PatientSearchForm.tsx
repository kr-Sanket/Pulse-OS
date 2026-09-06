// The Health ID input and its Search button. Presentational: it owns the text being typed
// and reports a submission; the hook above decides what a search means.

import { Search } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button, Input, Label } from "@pulseos/ui";

export interface PatientSearchFormProps {
  /** Prefills the field — the dashboard hands a Health ID over through the URL. */
  initialHealthId?: string;
  searching: boolean;
  /** False while the clinician's profile is not ACTIVE (ADR-015). */
  enabled?: boolean;
  onSearch: (healthId: string) => void;
}

export function PatientSearchForm({
  initialHealthId = "",
  searching,
  enabled = true,
  onSearch,
}: PatientSearchFormProps) {
  const [healthId, setHealthId] = useState(initialHealthId);
  const disabled = searching || !enabled;

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSearch(healthId);
  }

  return (
    <form className="space-y-3" onSubmit={submit}>
      <div className="space-y-2">
        <Label htmlFor="patient-health-id">Pulse Health ID</Label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input
            id="patient-health-id"
            value={healthId}
            onChange={(event) => setHealthId(event.target.value)}
            placeholder="PHI-IND-2026-1QE8DVR"
            autoComplete="off"
            spellCheck={false}
            disabled={disabled}
            className="h-10 font-mono tracking-tight sm:flex-1"
          />
          <Button type="submit" size="lg" className="justify-center gap-2" disabled={disabled}>
            <Search className="size-4" aria-hidden />
            {searching ? "Searching…" : "Search"}
          </Button>
        </div>
      </div>
      <p className="text-muted-foreground text-xs leading-relaxed">
        Ask the patient for the ID printed on their PulseOS card. Searching shows only which kinds
        of record exist — never their contents.
      </p>
    </form>
  );
}
