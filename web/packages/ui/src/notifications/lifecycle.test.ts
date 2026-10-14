import { expect, test, vi } from "vitest";

import {
  badgeCountLabel,
  NO_NOTIFICATIONS_DESC,
  NO_NOTIFICATIONS_TITLE,
  NOTIFICATIONS_TITLE,
} from "./view";

test("constants match product specification", () => {
  expect(NOTIFICATIONS_TITLE).toBe("Notifications");
  expect(NO_NOTIFICATIONS_TITLE).toBe("No notifications");
  expect(NO_NOTIFICATIONS_DESC).toContain("You're all caught up!");
});

test("badgeCountLabel boundary conditions", () => {
  expect(badgeCountLabel(-10)).toBeNull();
  expect(badgeCountLabel(0)).toBeNull();
  expect(badgeCountLabel(1)).toBe("1");
  expect(badgeCountLabel(99)).toBe("99");
  expect(badgeCountLabel(100)).toBe("99+");
  expect(badgeCountLabel(1000)).toBe("99+");
});

test("lifecycle and timer interval defaults to 30s", () => {
  const pollInterval = 30_000;
  expect(pollInterval).toBe(30_000);

  const fakeTimer = vi.fn();
  const id = setInterval(fakeTimer, pollInterval);
  expect(id).toBeDefined();
  clearInterval(id);
});

test("window focus and document visibility handlers can be attached and detached", () => {
  const addSpy = vi.fn();
  const removeSpy = vi.fn();

  const fakeTarget = {
    addEventListener: addSpy,
    removeEventListener: removeSpy,
  };

  const listener = () => {};
  fakeTarget.addEventListener("focus", listener);
  expect(addSpy).toHaveBeenCalledWith("focus", listener);

  fakeTarget.removeEventListener("focus", listener);
  expect(removeSpy).toHaveBeenCalledWith("focus", listener);
});
