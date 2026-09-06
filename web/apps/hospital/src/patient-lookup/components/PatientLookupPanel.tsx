// Step one of an upload: find the patient, then say out loud that they are the right one.
//
// Presentational — every string and every transition was decided in patient-lookup/view.ts.
// The confirmation is a checkbox rather than a second button because it must be *revocable*:
// an operator who reads the name and realises it is wrong unticks it, and the upload closes
// again without them having to undo anything else.

import { CircleCheck, Search, TriangleAlert, UserRound } from "lucide-react";
import type { FormEvent } from "react";

import { Button, Card, CardContent, Checkbox, Input, Label, Separator } from "@pulseos/ui";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/shell/IconChip";
import { MAX_HEALTH_ID_LENGTH } from "@/patient-lookup/api";
import { HEALTH_ID_CAUTION, type LookupSession } from "@/patient-lookup/view";

export interface PatientLookupPanelProps {
  session: LookupSession;
  searchable: boolean;
  /** False while the hospital is PENDING — nothing downstream can be uploaded anyway. */
  enabled: boolean;
  onHealthIdChange: (raw: string) => void;
  onFind: () => void;
  onConfirmedChange: (confirmed: boolean) => void;
}

export function PatientLookupPanel({
  session,
  searchable,
  enabled,
  onHealthIdChange,
  onFind,
  onConfirmedChange,
}: PatientLookupPanelProps) {
  const searching = session.state.kind === "searching";

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onFind();
  }

  return (
    <Card className="[--card-spacing:--spacing(6)]">
      <CardContent className="space-y-5">
        <form className="space-y-3" onSubmit={submit}>
          <div className="space-y-2">
            <Label htmlFor="healthId">Pulse Health ID</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id="healthId"
                value={session.healthId}
                onChange={(event) => onHealthIdChange(event.target.value)}
                placeholder="PHI-IND-2026-7K3M99X"
                maxLength={MAX_HEALTH_ID_LENGTH}
                disabled={!enabled || searching}
                autoComplete="off"
                spellCheck={false}
                aria-describedby="healthId-hint"
                className="h-10 font-mono tracking-tight uppercase"
              />
              <Button
                type="submit"
                variant="outline"
                className="h-10 shrink-0 gap-2"
                disabled={!enabled || !searchable}
              >
                <Search className="size-4" aria-hidden />
                {searching ? "Finding…" : "Find Patient"}
              </Button>
            </div>
            <p id="healthId-hint" className="text-muted-foreground text-xs leading-relaxed">
              {HEALTH_ID_CAUTION}
            </p>
          </div>
        </form>

        {session.state.kind === "error" ? (
          <p
            role="alert"
            className="text-destructive flex items-start gap-2 text-sm leading-relaxed"
          >
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            {session.state.message}
          </p>
        ) : null}

        {session.state.kind === "found" ? (
          <>
            <Separator />
            <div className="space-y-4">
              <div className="flex items-start gap-4">
                <IconChip icon={UserRound} />
                <div className="min-w-0 flex-1">
                  <p className="text-muted-foreground text-xs">Patient found</p>
                  <h3 className="text-foreground truncate text-[15px] font-medium">
                    {session.state.patient.fullName}
                  </h3>
                </div>
              </div>

              <dl className="grid gap-5 sm:grid-cols-2">
                <Detail label="Name">{session.state.patient.fullName}</Detail>
                <Detail label="Health ID">
                  <span className="font-mono text-[13px] tracking-tight">
                    {session.state.patient.healthId}
                  </span>
                </Detail>
              </dl>

              <label className="border-border hover:bg-muted/40 flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition-colors">
                <Checkbox
                  checked={session.confirmed}
                  disabled={!enabled}
                  onCheckedChange={(checked) => onConfirmedChange(checked === true)}
                  aria-label="Confirm this is the intended patient"
                />
                <span className="text-foreground text-sm leading-relaxed">
                  I confirm this is the intended patient.
                  <span className="text-muted-foreground block text-xs">
                    Read the name back to them before you tick this.
                  </span>
                </span>
              </label>

              {session.confirmed ? (
                <p className="text-success flex items-start gap-2 text-xs leading-relaxed">
                  <CircleCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  Confirmed. The document below will be filed against{" "}
                  {session.state.patient.fullName}.
                </p>
              ) : null}
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
