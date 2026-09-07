// The a hospital administrator login page's copy, as data. No React, no DOM.
//
// Narrower than the doctor portal's wording on purpose: this portal admits the
// hospital's administrator, not any clinician the hospital has registered.
//
// Everything genuinely shared — the "Welcome!" heading, the button label, the sanitized
// failure sentence, the brand tagline — lives in @pulseos/ui and is deliberately absent
// here, so a portal cannot fork the wording that is supposed to be identical.
//
// PulseOS authenticates through the Firebase Google popup and nothing else: there is no
// credential mechanism, so there is no email field, no password field and no account
// recovery to describe. `describesNoCredentialFlow` below is the executable form of that
// rule, and the test asserts it.

export interface LoginCopy {
  /** Named in the brand panel, under the wordmark. */
  portalName: string;
  /** The single line under the heading: who signs in here, and with which account. */
  subtitle: string;
  /** Shown by LoadingScreen while the auth provider restores a session. */
  checkingSession: string;
}

export const LOGIN_COPY: LoginCopy = {
  portalName: "Hospital portal",
  subtitle: "Sign in with the Google account registered as your hospital’s administrator.",
  checkingSession: "Checking your session…",
};

/**
 * Vocabulary that would imply an authentication method PulseOS does not have.
 *
 * A reviewer skimming a login screen reads "password" as a promise. Keeping the list here
 * and asserting it in the test means the copy cannot quietly start describing a credential
 * flow that no code path implements.
 */
// "register" is deliberately absent: a clinician's account is *registered at* their
// hospital, which is provisioning, not credential self-service. The phrases below have no
// innocent reading on a login screen.
const CREDENTIAL_WORDS = [
  "password",
  "email address",
  "forgot",
  "remember me",
  "sign up",
  "create an account",
];

export function describesNoCredentialFlow(copy: LoginCopy): boolean {
  const text = `${copy.portalName} ${copy.subtitle} ${copy.checkingSession}`.toLowerCase();
  return CREDENTIAL_WORDS.every((word) => !text.includes(word));
}
