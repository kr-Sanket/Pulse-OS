import { expect, test } from "vitest";

import {
  HEALTH_ID_CAUTION,
  IDLE_SESSION,
  INVALID_HEALTH_ID,
  canSearch,
  confirmedPatient,
  looksLikeHealthId,
  normalizeHealthId,
  startSearch,
  withConfirmation,
  withError,
  withHealthId,
  withResult,
  type LookupSession,
  type PatientIdentity,
} from "./view";

const ASHA: PatientIdentity = { healthId: "PHI-IND-2026-7K3M99X", fullName: "Asha Rao" };
const BHARAT: PatientIdentity = { healthId: "PHI-IND-2026-1QE8DVR", fullName: "Bharat Singh" };

/** A session that has looked Asha up and confirmed her — the only state that permits an
 * upload, and the baseline every rule below is measured against. */
function confirmedSession(): LookupSession {
  const typed = withHealthId(IDLE_SESSION, ASHA.healthId);
  return withConfirmation(withResult(startSearch(typed), ASHA), true);
}

// -- Health ID handling --------------------------------------------------------------

test("a Health ID is normalised the way ADR-012 stores it", () => {
  expect(normalizeHealthId("  phi-ind-2026-7k3m99x  ")).toBe("PHI-IND-2026-7K3M99X");
});

test("the shape check accepts a real ID and rejects a malformed one", () => {
  expect(looksLikeHealthId("phi-ind-2026-7k3m99x")).toBe(true);
  expect(looksLikeHealthId("PHI-IND-2026-7K3M99")).toBe(false);
  expect(looksLikeHealthId("ABC-IND-2026-7K3M99X")).toBe(false);
  expect(looksLikeHealthId("")).toBe(false);
});

test("the shape check does not pretend to verify the check character", () => {
  // ISO 7064 lives once, in app/modules/patients/health_id.py. The backend runs it on
  // every lookup and answers 422; a TypeScript copy would be free to drift.
  expect(looksLikeHealthId("PHI-IND-2026-7K3M99A")).toBe(true);
  expect(INVALID_HEALTH_ID).toContain("PHI-IND-YYYY-XXXXXXC");
});

test("the caution names both facts an operator cannot discover for themselves", () => {
  expect(HEALTH_ID_CAUTION).toContain("confirm their name before uploading");
  expect(HEALTH_ID_CAUTION).toContain("cannot be moved or removed");
});

// -- initial state ---------------------------------------------------------------------

test("a fresh session has nothing looked up, nothing confirmed and permits no upload", () => {
  expect(IDLE_SESSION.state.kind).toBe("idle");
  expect(IDLE_SESSION.confirmed).toBe(false);
  expect(confirmedPatient(IDLE_SESSION)).toBeNull();
});

test("searching needs a plausible Health ID, and not one already in flight", () => {
  expect(canSearch(IDLE_SESSION)).toBe(false);
  expect(canSearch(withHealthId(IDLE_SESSION, "rubbish"))).toBe(false);
  expect(canSearch(withHealthId(IDLE_SESSION, ASHA.healthId))).toBe(true);
  expect(canSearch(startSearch(withHealthId(IDLE_SESSION, ASHA.healthId)))).toBe(false);
});

// -- a successful lookup ----------------------------------------------------------------

test("finding a patient does not confirm them — the operator must say so", () => {
  const found = withResult(startSearch(withHealthId(IDLE_SESSION, ASHA.healthId)), ASHA);

  expect(found.state).toEqual({ kind: "found", patient: ASHA });
  expect(found.confirmed).toBe(false);
  expect(confirmedPatient(found)).toBeNull();
});

test("a confirmed lookup is what permits an upload", () => {
  expect(confirmedPatient(confirmedSession())).toEqual(ASHA);
});

test("unticking the confirmation closes the upload again", () => {
  const unconfirmed = withConfirmation(confirmedSession(), false);

  expect(confirmedPatient(unconfirmed)).toBeNull();
});

// -- failure ------------------------------------------------------------------------------

test("a failed lookup shows no patient and permits no upload", () => {
  const failed = withError(startSearch(withHealthId(IDLE_SESSION, ASHA.healthId)), "no such ID");

  expect(failed.state).toEqual({ kind: "error", message: "no such ID" });
  expect(confirmedPatient(failed)).toBeNull();
});

test("a failed lookup never leaves the previous patient on screen", () => {
  // The dangerous version of this bug: search A, confirm, search B, B fails, and A is still
  // shown and still confirmed.
  const afterFailure = withError(confirmedSession(), "no such ID");

  expect(afterFailure.state.kind).toBe("error");
  expect(afterFailure.confirmed).toBe(false);
  expect(confirmedPatient(afterFailure)).toBeNull();
});

test("starting a new search drops the previous result immediately", () => {
  const searching = startSearch(confirmedSession());

  expect(searching.state.kind).toBe("searching");
  expect(confirmedPatient(searching)).toBeNull();
});

// -- the rule this module exists for -----------------------------------------------------

test("changing the Health ID clears the lookup and the confirmation", () => {
  const changed = withHealthId(confirmedSession(), BHARAT.healthId);

  expect(changed.state.kind).toBe("idle");
  expect(changed.confirmed).toBe(false);
  expect(confirmedPatient(changed)).toBeNull();
});

test("even one edited character discards a confirmation", () => {
  const changed = withHealthId(confirmedSession(), `${ASHA.healthId.slice(0, -1)}A`);

  expect(confirmedPatient(changed)).toBeNull();
});

test("clearing the field discards the confirmation", () => {
  expect(confirmedPatient(withHealthId(confirmedSession(), ""))).toBeNull();
});

test("re-typing the same ID in a different case keeps a confirmation that is still true", () => {
  const recased = withHealthId(confirmedSession(), ASHA.healthId.toLowerCase());

  expect(confirmedPatient(recased)).toEqual(ASHA);
});

test("a confirmation can never belong to a Health ID other than the one looked up", () => {
  // The invariant, asserted directly rather than through the transitions that maintain it:
  // a hand-built session whose field and result disagree authorises nothing.
  const mismatched: LookupSession = {
    healthId: BHARAT.healthId,
    state: { kind: "found", patient: ASHA },
    confirmed: true,
  };

  expect(confirmedPatient(mismatched)).toBeNull();
});

test("a confirmation cannot be set on a session that has found nobody", () => {
  expect(withConfirmation(IDLE_SESSION, true).confirmed).toBe(false);
  expect(withConfirmation(withError(IDLE_SESSION, "nope"), true).confirmed).toBe(false);
  expect(withConfirmation(startSearch(IDLE_SESSION), true).confirmed).toBe(false);
});
