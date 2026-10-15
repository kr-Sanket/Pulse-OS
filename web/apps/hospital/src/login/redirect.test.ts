import { describe, expect, it } from "vitest";

import { getSafeRedirectPath } from "./redirect";

describe("getSafeRedirectPath", () => {
  it("preserves valid internal paths", () => {
    expect(getSafeRedirectPath("/admin/verification")).toBe("/admin/verification");
    expect(getSafeRedirectPath("/doctors")).toBe("/doctors");
    expect(getSafeRedirectPath("/uploads/rec-123")).toBe("/uploads/rec-123");
    expect(getSafeRedirectPath("/admin/verification?filter=PENDING#section")).toBe(
      "/admin/verification?filter=PENDING#section",
    );
  });

  it("extracts path from router Location objects", () => {
    expect(
      getSafeRedirectPath({
        pathname: "/admin/verification",
        search: "?filter=PENDING",
        hash: "",
      }),
    ).toBe("/admin/verification?filter=PENDING");

    expect(
      getSafeRedirectPath({
        pathname: "/hospital",
      }),
    ).toBe("/hospital");
  });

  it("defaults to fallback '/' when input is null, undefined, or empty", () => {
    expect(getSafeRedirectPath(null)).toBe("/");
    expect(getSafeRedirectPath(undefined)).toBe("/");
    expect(getSafeRedirectPath("")).toBe("/");
    expect(getSafeRedirectPath("   ")).toBe("/");
    expect(getSafeRedirectPath({})).toBe("/");
  });

  it("prevents open redirect attacks via protocol-relative URLs", () => {
    expect(getSafeRedirectPath("//evil.com")).toBe("/");
    expect(getSafeRedirectPath("//evil.com/admin")).toBe("/");
    expect(getSafeRedirectPath("/\\evil.com")).toBe("/");
    expect(getSafeRedirectPath(" //evil.com")).toBe("/");
  });

  it("prevents open redirect attacks via absolute URLs and schemes", () => {
    expect(getSafeRedirectPath("https://evil.com")).toBe("/");
    expect(getSafeRedirectPath("http://evil.com/admin/verification")).toBe("/");
    expect(getSafeRedirectPath("javascript:alert(1)")).toBe("/");
    expect(getSafeRedirectPath("data:text/html,evil")).toBe("/");
  });

  it("rejects paths containing backslashes", () => {
    expect(getSafeRedirectPath("/admin\\verification")).toBe("/");
    expect(getSafeRedirectPath("\\evil.com")).toBe("/");
  });

  it("prevents redirect loops back to /login", () => {
    expect(getSafeRedirectPath("/login")).toBe("/");
    expect(getSafeRedirectPath("/login?redirect=something")).toBe("/");
  });

  it("respects custom fallback when provided", () => {
    expect(getSafeRedirectPath("https://evil.com", "/dashboard")).toBe("/dashboard");
    expect(getSafeRedirectPath(null, "/dashboard")).toBe("/dashboard");
  });
});
