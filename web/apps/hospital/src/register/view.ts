// Registration form rules and the wording of what happens next. Pure functions, no React.
//
// Validation here is deliberately thin: required, trimmed, non-empty, and within the API's
// own length limits (imported from api.ts, never restated). Everything else — whether this
// account already holds another role, whether the server can reach its auth provider — is
// the server's ruling, and the form surfaces its answer rather than predicting it.

import {
  MAX_ADMIN_FULL_NAME_LENGTH,
  MAX_HOSPITAL_ADDRESS_LENGTH,
  MAX_HOSPITAL_NAME_LENGTH,
  type HospitalRegistrationDraft,
} from "./api";

export const EMPTY_DRAFT: HospitalRegistrationDraft = {
  hospitalName: "",
  hospitalAddress: "",
  adminFullName: "",
};

export type DraftField = keyof HospitalRegistrationDraft;

export const FIELD_LABELS: Readonly<Record<DraftField, string>> = {
  hospitalName: "Hospital name",
  hospitalAddress: "Address",
  adminFullName: "Your full name",
};

const MAX_LENGTHS: Readonly<Record<DraftField, number>> = {
  hospitalName: MAX_HOSPITAL_NAME_LENGTH,
  hospitalAddress: MAX_HOSPITAL_ADDRESS_LENGTH,
  adminFullName: MAX_ADMIN_FULL_NAME_LENGTH,
};

/** Address is the only field the API accepts as absent. */
const OPTIONAL_FIELDS: ReadonlySet<DraftField> = new Set<DraftField>(["hospitalAddress"]);

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
  draft: HospitalRegistrationDraft,
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

export function isSendable(draft: HospitalRegistrationDraft): boolean {
  return Object.keys(draftProblems(draft)).length === 0;
}

/** The warning under the hospital-name field.
 *
 * This form always creates a *new* hospital — there is no endpoint that adds a second
 * administrator to an existing one, so an administrator who registers a hospital already on
 * PulseOS silently ends up with a duplicate organisation under a different HID, holding none
 * of the original's records. Saying so costs one line and is far cheaper than the support
 * conversation that follows. */
export const DUPLICATE_WARNING =
  "This creates a new hospital on PulseOS. If yours is already registered, ask its existing " +
  "administrator instead — registering again would create a second, separate hospital.";

/** Copy for the panel shown once registration has been accepted. Reuses the portal's own
 * account vocabulary: what happened, who acts next, and what unlocks when they do. */
export const REGISTERED = {
  title: "Hospital registered",
  body:
    "Your hospital has been created on PulseOS and is waiting for verification. Only a " +
    "PulseOS system administrator can verify it.",
  points: [
    "A PulseOS system administrator verifies your hospital.",
    "Until then, doctors cannot register to it and no records can be uploaded.",
    "Once verified, you can activate your doctors and upload records for a Pulse Health ID.",
  ],
} as const;
