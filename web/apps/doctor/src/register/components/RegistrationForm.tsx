// The four fields the API accepts, and nothing else.
//
// Presentational: the draft, its problems and the in-flight state all arrive as props. No
// hospital lookup — there is no endpoint that lists hospitals, so the Hospital ID is a plain
// text field, exactly as the API takes it.

import { UserPlus } from "lucide-react";
import type { FormEvent } from "react";

import { Button, Input, Label } from "@pulseos/ui";

import {
  MAX_FULL_NAME_LENGTH,
  MAX_HOSPITAL_HID_LENGTH,
  MAX_REGISTRATION_NUMBER_LENGTH,
  MAX_SPECIALTY_LENGTH,
  type DoctorRegistrationDraft,
} from "@/register/api";
import { FIELD_LABELS, type DraftField } from "@/register/view";

export interface RegistrationFormProps {
  draft: DoctorRegistrationDraft;
  problems: Readonly<Partial<Record<DraftField, string>>>;
  submitting: boolean;
  /** Why the API refused the last attempt, if it did. */
  error: string | null;
  onFieldChange: (field: DraftField, value: string) => void;
  onSubmit: () => void;
}

const MAX_LENGTHS: Readonly<Record<DraftField, number>> = {
  fullName: MAX_FULL_NAME_LENGTH,
  registrationNumber: MAX_REGISTRATION_NUMBER_LENGTH,
  specialty: MAX_SPECIALTY_LENGTH,
  hospitalHid: MAX_HOSPITAL_HID_LENGTH,
};

const FIELDS: readonly {
  field: DraftField;
  placeholder: string;
  hint?: string;
  optional?: boolean;
  mono?: boolean;
}[] = [
  { field: "fullName", placeholder: "Dr Meera Sharma" },
  {
    field: "registrationNumber",
    placeholder: "MCI-2019-44718",
    hint: "Your medical council registration number.",
  },
  { field: "specialty", placeholder: "Cardiology", optional: true },
  {
    field: "hospitalHid",
    placeholder: "HID-0001",
    hint: "The PulseOS ID of the hospital you practise at — ask your administrator.",
    mono: true,
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
      {FIELDS.map(({ field, placeholder, hint, optional, mono }) => {
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
              className={mono === true ? "h-10 font-mono tracking-tight" : "h-10"}
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
        <UserPlus className="size-4" aria-hidden />
        {submitting ? "Submitting…" : "Register as a clinician"}
      </Button>
    </form>
  );
}
