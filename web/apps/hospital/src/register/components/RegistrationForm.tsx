// The three fields the API accepts, and nothing else.
//
// Presentational: the draft, its problems and the in-flight state all arrive as props. The
// hospital's HID is not a field — the server draws it (ADR-015) and returns it, so there is
// nothing here for an administrator to choose.

import { Building2 } from "lucide-react";
import type { FormEvent } from "react";

import { Button, Input, Label } from "@pulseos/ui";

import {
  MAX_ADMIN_FULL_NAME_LENGTH,
  MAX_HOSPITAL_ADDRESS_LENGTH,
  MAX_HOSPITAL_NAME_LENGTH,
  type HospitalRegistrationDraft,
} from "@/register/api";
import { DUPLICATE_WARNING, FIELD_LABELS, type DraftField } from "@/register/view";

export interface RegistrationFormProps {
  draft: HospitalRegistrationDraft;
  problems: Readonly<Partial<Record<DraftField, string>>>;
  submitting: boolean;
  /** Why the API refused the last attempt, if it did. */
  error: string | null;
  onFieldChange: (field: DraftField, value: string) => void;
  onSubmit: () => void;
}

const MAX_LENGTHS: Readonly<Record<DraftField, number>> = {
  hospitalName: MAX_HOSPITAL_NAME_LENGTH,
  hospitalAddress: MAX_HOSPITAL_ADDRESS_LENGTH,
  adminFullName: MAX_ADMIN_FULL_NAME_LENGTH,
};

const FIELDS: readonly {
  field: DraftField;
  placeholder: string;
  hint?: string;
  optional?: boolean;
}[] = [
  {
    field: "hospitalName",
    placeholder: "Tata Main Hospital",
    hint: DUPLICATE_WARNING,
  },
  { field: "hospitalAddress", placeholder: "Bistupur, Jamshedpur", optional: true },
  {
    field: "adminFullName",
    placeholder: "Anita Rao",
    hint: "Recorded as this hospital's administrator on PulseOS.",
  },
];

export function RegistrationForm({
  draft,
  problems,
  submitting,
  error,
  onFieldChange,
  onSubmit,
}: RegistrationFormProps) {
  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="space-y-5" onSubmit={submit}>
      {FIELDS.map(({ field, placeholder, hint, optional }) => {
        const problem = problems[field];
        const hintId = `${field}-hint`;
        return (
          <div key={field} className="space-y-2">
            <Label htmlFor={field}>
              {FIELD_LABELS[field]}
              {optional === true ? (
                <span className="text-muted-foreground font-normal">(optional)</span>
              ) : null}
            </Label>
            <Input
              id={field}
              value={draft[field]}
              onChange={(event) => onFieldChange(field, event.target.value)}
              placeholder={placeholder}
              maxLength={MAX_LENGTHS[field]}
              disabled={submitting}
              autoComplete="off"
              aria-invalid={problem !== undefined}
              aria-describedby={hint === undefined ? undefined : hintId}
              className="h-10"
            />
            {problem === undefined ? (
              hint === undefined ? null : (
                <p id={hintId} className="text-muted-foreground text-xs leading-relaxed">
                  {hint}
                </p>
              )
            ) : (
              <p role="alert" className="text-destructive text-xs leading-relaxed">
                {problem}
              </p>
            )}
          </div>
        );
      })}

      {error === null ? null : (
        <p role="alert" className="text-destructive text-sm leading-relaxed">
          {error}
        </p>
      )}

      <Button type="submit" className="w-full justify-center gap-2" disabled={submitting}>
        <Building2 className="size-4" aria-hidden />
        {submitting ? "Submitting…" : "Register this hospital"}
      </Button>
    </form>
  );
}
