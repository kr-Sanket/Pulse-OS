import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";
import { useCurrentUserRole, type CurrentUserRoleState } from "./useCurrentUserRole";

describe("useCurrentUserRole", () => {
  it("initializes with loading: true and null role before resolution", () => {
    let capturedState: CurrentUserRoleState | null = null;

    function TestComponent() {
      capturedState = useCurrentUserRole({} as PulseOSClient);
      return null;
    }

    renderToString(<TestComponent />);

    expect(capturedState).toEqual({
      role: null,
      loading: true,
      error: null,
    });
  });
});
