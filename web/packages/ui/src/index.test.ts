import { expect, test } from "vitest";

import { UI_PACKAGE_NAME } from "./index";

// Placeholder test: proves the vitest wiring end-to-end until real components arrive (M0.3).
test("ui package exports its name", () => {
  expect(UI_PACKAGE_NAME).toBe("@pulseos/ui");
});
