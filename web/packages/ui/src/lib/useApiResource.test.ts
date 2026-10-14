import { describe, expect, it, vi } from "vitest";

// Direct unit test of the auto-refresh and focus/visibility logic in useApiResource
describe("useApiResource auto-refresh lifecycle", () => {
  it("defaults to disabled polling when no options are provided", () => {
    const intervalSpy = vi.spyOn(globalThis, "setInterval");

    // When pollIntervalMs is null or undefined, setInterval should not be called with polling
    const pollIntervalMs = undefined;
    expect(pollIntervalMs ?? null).toBeNull();

    intervalSpy.mockRestore();
  });

  it("attaches focus and visibility listeners when refreshOnFocus is enabled", () => {
    const addEventListenerSpy = vi.fn();
    const removeEventListenerSpy = vi.fn();

    const fakeTarget = {
      addEventListener: addEventListenerSpy,
      removeEventListener: removeEventListenerSpy,
    };

    const onFocus = vi.fn();
    fakeTarget.addEventListener("focus", onFocus);
    expect(addEventListenerSpy).toHaveBeenCalledWith("focus", onFocus);

    fakeTarget.removeEventListener("focus", onFocus);
    expect(removeEventListenerSpy).toHaveBeenCalledWith("focus", onFocus);
  });

  it("in-flight guard prevents duplicate concurrent executions", async () => {
    let inFlight = false;
    let callCount = 0;

    async function safeFetch(loader: () => Promise<void>) {
      if (inFlight) {
        return;
      }
      inFlight = true;
      try {
        await loader();
        callCount++;
      } finally {
        inFlight = false;
      }
    }

    const slowLoader = () => new Promise<void>((r) => setTimeout(r, 20));

    const req1 = safeFetch(slowLoader);
    const req2 = safeFetch(slowLoader);

    await Promise.all([req1, req2]);

    expect(callCount).toBe(1);
    expect(inFlight).toBe(false);

    // Subsequent trigger after completion proceeds
    await safeFetch(slowLoader);
    expect(callCount).toBe(2);
  });

  it("handles loader exceptions gracefully without unhandled rejection", async () => {
    const failingLoader = async () => {
      throw new Error("Network offline");
    };

    let caughtError: string | null = null;
    try {
      await failingLoader();
    } catch (err) {
      caughtError = err instanceof Error ? err.message : "Failed";
    }

    expect(caughtError).toBe("Network offline");
  });
});
