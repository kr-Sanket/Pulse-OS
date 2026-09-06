// The lookup-and-confirm state machine, as pure functions. No React.
//
// This file exists because the safety property of the whole slice is a *state* rule, not a
// rendering one: a confirmation must belong to the exact Health ID that produced it, and it
// must not survive that Health ID changing. Expressed as transitions over one immutable
// session value, each rule is a line of code and a unit test rather than a scattering of
// setState calls that have to be read together to be trusted.

import type { PatientIdentity } from "./api";

export type { PatientIdentity };

/** ADR-012 stores canonical uppercase; a reception desk types whatever it types. */
export function normalizeHealthId(input: string): string {
  return input.trim().toUpperCase();
}

/**
 * Format-only check: the prefix, a four-digit year, and seven characters of body plus
 * check character.
 *
 * Deliberately *not* the ISO 7064 check-character verification — that algorithm lives once,
 * in app/modules/patients/health_id.py, and a TypeScript copy would be free to drift. The
 * backend runs it on every lookup and answers 422 with "not a valid Pulse Health ID", which
 * is precisely the offline typo detection ADR-012 designed the check character for. This
 * only stops an obviously malformed value from costing a round trip.
 */
const HEALTH_ID_SHAPE = /^PHI-IND-\d{4}-[0-9A-Z]{7}$/;

export function looksLikeHealthId(input: string): boolean {
  return HEALTH_ID_SHAPE.test(normalizeHealthId(input));
}

export const INVALID_HEALTH_ID =
  "That is not a Pulse Health ID. The format is PHI-IND-YYYY-XXXXXXC.";

/** The standing caution above the field. A hospital cannot move or delete a record once it
 * is filed, so the Health ID is the only thing standing between a document and the wrong
 * patient's history. */
export const HEALTH_ID_CAUTION =
  "Look the patient up and confirm their name before uploading. A document filed against " +
  "the wrong Health ID cannot be moved or removed.";

export type LookupState =
  | { kind: "idle" }
  | { kind: "searching" }
  | { kind: "found"; patient: PatientIdentity }
  | { kind: "error"; message: string };

export interface LookupSession {
  /** Raw input, exactly as typed — the field is controlled and must not fight the typist. */
  healthId: string;
  state: LookupState;
  /** Only ever meaningful against a `found` state for this same Health ID. */
  confirmed: boolean;
}

export const IDLE_SESSION: LookupSession = {
  healthId: "",
  state: { kind: "idle" },
  confirmed: false,
};

/**
 * Type into the Health ID field.
 *
 * **Changing the ID discards the previous result and the confirmation with it.** That is
 * the rule this whole module exists to make unmissable: a confirmation for Health ID A must
 * never authorise an upload for Health ID B. Comparison is on the normalised value, so
 * merely changing the case of the same ID keeps a confirmation that is still true.
 */
export function withHealthId(session: LookupSession, raw: string): LookupSession {
  if (normalizeHealthId(raw) === normalizeHealthId(session.healthId)) {
    return { ...session, healthId: raw };
  }
  return { healthId: raw, state: { kind: "idle" }, confirmed: false };
}

/** A search is starting: any earlier result stops being shown, so nothing stale survives. */
export function startSearch(session: LookupSession): LookupSession {
  return { ...session, state: { kind: "searching" }, confirmed: false };
}

/** A patient came back. Confirmation always starts false — finding someone is not
 * confirming them, and the operator has to say so. */
export function withResult(session: LookupSession, patient: PatientIdentity): LookupSession {
  return { ...session, state: { kind: "found", patient }, confirmed: false };
}

/** The lookup failed. No previous patient is left on screen to be confirmed by mistake. */
export function withError(session: LookupSession, message: string): LookupSession {
  return { ...session, state: { kind: "error", message }, confirmed: false };
}

/** Tick or untick the confirmation. Only a `found` session can hold one; anything else
 * forces false, so a checkbox cannot be left ticked over an error or an empty result. */
export function withConfirmation(session: LookupSession, confirmed: boolean): LookupSession {
  return { ...session, confirmed: confirmed && session.state.kind === "found" };
}

/**
 * The patient this session authorises an upload for, or null.
 *
 * Three conditions, all required: a successful lookup, an explicit confirmation, and a
 * Health ID that still matches the one the lookup answered for. The third is redundant
 * while `withHealthId` is the only way to edit the field — and it is kept anyway, because
 * it is the invariant the upload actually depends on, and a future edit path that forgot to
 * reset would otherwise silently file a document against the wrong person.
 */
export function confirmedPatient(session: LookupSession): PatientIdentity | null {
  if (session.state.kind !== "found" || !session.confirmed) {
    return null;
  }
  return normalizeHealthId(session.healthId) === session.state.patient.healthId
    ? session.state.patient
    : null;
}

/** Whether pressing Find Patient would do anything: a plausible ID, and no search already
 * running. The button is guarded here rather than only by `disabled`, which settles a render
 * late. */
export function canSearch(session: LookupSession): boolean {
  return session.state.kind !== "searching" && looksLikeHealthId(session.healthId);
}
