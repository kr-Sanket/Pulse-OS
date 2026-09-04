// Registration form rules and the wording of what happens next. Pure functions, no React.
//
// Validation here is deliberately thin: required, trimmed, non-empty, and within the API's
// own length limits (imported from api.ts, never restated). Everything else — whether the
// hospital exists, whether it is verified, whether this account already holds another role
// — is the server's ruling, and the form surfaces its answer rather than predicting it.

import {
  MAX_FULL_NAME_LENGTH,
  MAX_HOSPITAL_HID_LENGTH,
  MAX_REGISTRATION_NUMBER_LENGTH,
  MAX_SPECIALTY_LENGTH,
  type DoctorRegistrationDraft,
} from "./api";

export const EMPTY_DRAFT: DoctorRegistrationDraft = {
  fullName: "",
  registrationNumber: "",
  specialty: "",
  hospitalHid: "",
};

export type DraftField = keyof DoctorRegistrationDraft;

export const FIELD_LABELS: Readonly<Record<DraftField, string>> = {
  fullName: "Full name",
  registrationNumber: "Registration number",
  specialty: "Specialty",
  hospitalHid: "Hospital ID",
};

const MAX_LENGTHS: Readonly<Record<DraftField, number>> = {
  fullName: MAX_FULL_NAME_LENGTH,
  registrationNumber: MAX_REGISTRATION_NUMBER_LENGTH,
  specialty: MAX_SPECIALTY_LENGTH,
  hospitalHid: MAX_HOSPITAL_HID_LENGTH,
};

/** Specialty is the only field the API accepts as absent. */
const OPTIONAL_FIELDS: ReadonlySet<DraftField> = new Set<DraftField>(["specialty"]);

/** Why one field cannot be sent, or null when it can. */
export function fieldProblem(field: DraftField, value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) {
    return OPTIONAL_FIELDS.has(field) ? null : `${FIELD_LABELS[field]} is required.`;
  }
  if (trimmed.length > MAX_LENGTHS[field]) {
    return `${FIELD_LABELS[field]} must be ${MAX_LENGTHS[field]} characters or fewer.`;
  }
  return null;
}

/** Every field's problem, keyed by field — empty when the draft is sendable. */
export function draftProblems(
  draft: DoctorRegistrationDraft,
): Readonly<Partial<Record<DraftField, string>>> {
  const problems: Partial<Record<DraftField, string>> = {};
  for (const field of Object.keys(draft) as DraftField[]) {
    const problem = fieldProblem(field, draft[field]);
    if (problem !== null) {
      problems[field] = problem;
    }
  }
  return problems;
}

export function isSendable(draft: DoctorRegistrationDraft): boolean {
  return Object.keys(draftProblems(draft)).length === 0;
}

/** Copy for the panel shown once registration has been accepted. Reuses the portal's own
 * account vocabulary: what happened, who acts next, and what unlocks when they do. */
export const REGISTERED = {
  title: "Registration submitted",
  body:
    "Your clinician profile has been created and is waiting for approval. Only a hospital " +
    "administrator can activate it.",
  points: [
    "A hospital administrator at your hospital activates your profile.",
    "Until then you can sign in, but patient search stays unavailable.",
    "Once activated, you can search a Pulse Health ID and request access to records.",
  ],
} as const;
