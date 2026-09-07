import { expect, test } from "vitest";

import { LOGIN_COPY, describesNoCredentialFlow, type LoginCopy } from "./view";

test("the brand panel names this portal", () => {
  expect(LOGIN_COPY.portalName).toBe("Patient portal");
});

test("the subtitle says who signs in here", () => {
  expect(LOGIN_COPY.subtitle).toBe("Sign in to see your Pulse Health ID and profile.");
});

test("the session-restore message is the one LoadingScreen shows", () => {
  expect(LOGIN_COPY.checkingSession).toBe("Checking your session\u2026");
});

// -- the copy must not describe authentication PulseOS does not have ------------------

test("no wording implies a password, a reset or a credential sign-up", () => {
  expect(describesNoCredentialFlow(LOGIN_COPY)).toBe(true);
});

test("the guard actually catches credential wording", () => {
  const tempting: LoginCopy = {
    ...LOGIN_COPY,
    subtitle: "Enter your password, or use Forgot password to reset it.",
  };
  expect(describesNoCredentialFlow(tempting)).toBe(false);
});
