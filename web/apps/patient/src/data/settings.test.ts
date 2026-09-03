import { expect, test } from "vitest";

import {
  PREFERENCE_GROUPS,
  defaultPreferences,
  isDefaultPreferences,
  type PreferenceState,
} from "./settings";

const ALL_TOGGLES = PREFERENCE_GROUPS.flatMap((group) => group.toggles);

test("every preference id is unique, so no two switches share state", () => {
  const ids = ALL_TOGGLES.map((toggle) => toggle.id);

  expect(new Set(ids).size).toBe(ids.length);
});

test("defaults carry one entry per declared preference", () => {
  const defaults = defaultPreferences();

  expect(Object.keys(defaults)).toHaveLength(ALL_TOGGLES.length);
  for (const toggle of ALL_TOGGLES) {
    expect(defaults[toggle.id]).toBe(toggle.defaultOn);
  }
});

test("the default state counts as unchanged", () => {
  expect(isDefaultPreferences(defaultPreferences())).toBe(true);
});

test("flipping one switch marks the state as changed", () => {
  const first = ALL_TOGGLES[0];
  if (first === undefined) {
    throw new Error("expected at least one declared preference");
  }
  const changed: PreferenceState = { ...defaultPreferences(), [first.id]: !first.defaultOn };

  expect(isDefaultPreferences(changed)).toBe(false);
});
