import { expect, test } from "vitest";

import { ACCOUNT_SUSPENDED_DETAIL, isAccountSuspended } from "./apiResult";

test("only the suspended 403 counts as suspended", () => {
  expect(isAccountSuspended(403, { detail: ACCOUNT_SUSPENDED_DETAIL })).toBe(true);
  // An unprovisioned account is a 403 too, and must keep routing to onboarding.
  expect(isAccountSuspended(403, { detail: "Account is not provisioned for PulseOS." })).toBe(
    false,
  );
  expect(isAccountSuspended(403, {})).toBe(false);
  expect(isAccountSuspended(401, { detail: ACCOUNT_SUSPENDED_DETAIL })).toBe(false);
  expect(isAccountSuspended(403, undefined)).toBe(false);
});
