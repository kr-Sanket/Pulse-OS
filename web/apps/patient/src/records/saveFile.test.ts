import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { REVOKE_DELAY_MS, saveBlob } from "./saveFile";

interface FakeLink {
  href: string;
  download: string;
  rel: string;
  style: { display: string };
  click: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
}

let link: FakeLink;
const createObjectURL = vi.fn(() => "blob:fake-url");
const revokeObjectURL = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  link = {
    href: "",
    download: "",
    rel: "",
    style: { display: "" },
    click: vi.fn(),
    remove: vi.fn(),
  };
  vi.stubGlobal("document", {
    createElement: vi.fn(() => link),
    body: { appendChild: vi.fn() },
  });
  vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
});

test("the file is downloaded under its name and the link is removed", () => {
  const blob = new Blob(["{}"]);
  saveBlob(blob, "pulseos-fhir-export-2026-10-25.json");

  expect(createObjectURL).toHaveBeenCalledWith(blob);
  expect(link.href).toBe("blob:fake-url");
  expect(link.download).toBe("pulseos-fhir-export-2026-10-25.json");
  expect(link.click).toHaveBeenCalledOnce();
  expect(link.remove).toHaveBeenCalledOnce();
});

test("the object URL outlives the click and is revoked only after the delay", () => {
  saveBlob(new Blob(["{}"]), "f.json");

  vi.advanceTimersByTime(REVOKE_DELAY_MS - 1);
  expect(revokeObjectURL).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake-url");
});

test("the URL is still revoked when the click throws", () => {
  link.click.mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(() => saveBlob(new Blob(["{}"]), "f.json", 10)).toThrow("blocked");
  expect(link.remove).toHaveBeenCalledOnce();
  vi.advanceTimersByTime(10);
  expect(revokeObjectURL).toHaveBeenCalledOnce();
});
