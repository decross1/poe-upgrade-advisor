/**
 * TASK-207 (issue #29) — build-import surface. Snapshot coverage: empty
 * (initial), invalid-code (contract 422 path), success. Behavioral assertions
 * cover the submit contract (one POST per submit, trimmed paste, no empty
 * submits) and the non-422 failure state.
 *
 * The component does no network I/O (sourceHygiene); `onImport` is a stub.
 * The success summary is the same FE-local fixture the mock serves from disk
 * (web/mock/fixtures/ — single source of truth, never a copy).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BuildImport } from "../src/components/BuildImport";
import type { BuildImportResult } from "../src/components/BuildImport";
import type { BuildSummary } from "../src/generated/models/BuildSummary";

import buildSummaryJson from "../mock/fixtures/build_summary.json";

// JSON import widens strings; buildImportFixture.test.ts proves conformance
// with openapi's BuildSummary, so bind to the generated type here.
const buildSummary = buildSummaryJson as BuildSummary;

const ok: BuildImportResult = { ok: true, summary: buildSummary };
const invalid: BuildImportResult = { ok: false, status: 422 };
const unreachable: BuildImportResult = { ok: false, status: 0 };

function paste(code: string) {
  fireEvent.change(screen.getByLabelText("Path of Building code or XML"), {
    target: { value: code },
  });
}

describe("snapshot states (issue #29 acceptance criteria)", () => {
  it("empty — initial render, submit disabled until something is pasted", () => {
    const { container } = render(<BuildImport onImport={vi.fn()} />);
    expect(container).toMatchSnapshot();
  });

  it("invalid-code — the contract 422 path renders an alert and keeps the paste", async () => {
    const onImport = vi.fn<(code: string) => Promise<BuildImportResult>>().mockResolvedValue(invalid);
    const { container } = render(<BuildImport onImport={onImport} />);
    paste("eNq1notARealCode");
    fireEvent.click(screen.getByRole("button", { name: "Import build" }));
    await screen.findByRole("alert");
    expect(container).toMatchSnapshot();
  });

  it("success — the imported BuildSummary renders from the mock fixture", async () => {
    const onImport = vi.fn<(code: string) => Promise<BuildImportResult>>().mockResolvedValue(ok);
    const { container } = render(<BuildImport onImport={onImport} />);
    paste("eNq1RealCode");
    fireEvent.click(screen.getByRole("button", { name: "Import build" }));
    await screen.findByRole("status");
    expect(container).toMatchSnapshot();
  });
});

describe("submit contract (S2: one submit = one POST /build)", () => {
  it("submit is disabled with an empty or whitespace-only paste — no request fires", () => {
    const onImport = vi.fn<(code: string) => Promise<BuildImportResult>>();
    render(<BuildImport onImport={onImport} />);
    const button = screen.getByRole("button", { name: "Import build" });
    expect(button).toHaveProperty("disabled", true);
    paste("   \n  ");
    expect(button).toHaveProperty("disabled", true);
    fireEvent.click(button);
    expect(onImport).not.toHaveBeenCalled();
  });

  it("calls onImport exactly once per submit with the trimmed paste", async () => {
    const onImport = vi.fn<(code: string) => Promise<BuildImportResult>>().mockResolvedValue(ok);
    render(<BuildImport onImport={onImport} />);
    paste("  eNq1RealCode\n\n");
    fireEvent.click(screen.getByRole("button", { name: "Import build" }));
    await screen.findByRole("status");
    expect(onImport).toHaveBeenCalledTimes(1);
    expect(onImport).toHaveBeenCalledWith("eNq1RealCode");
  });

  it("the button is inert while a submit is in flight (no double POST)", async () => {
    let release!: (r: BuildImportResult) => void;
    const onImport = vi.fn(() => new Promise<BuildImportResult>((resolve) => (release = resolve)));
    render(<BuildImport onImport={onImport} />);
    paste("eNq1RealCode");
    fireEvent.click(screen.getByRole("button", { name: "Import build" }));
    const pending = screen.getByRole("button", { name: "Importing…" });
    expect(pending).toHaveProperty("disabled", true);
    fireEvent.click(pending);
    expect(onImport).toHaveBeenCalledTimes(1);
    release(ok);
    await screen.findByRole("status");
  });
});

describe("failure states", () => {
  it("422: alert text, paste preserved for editing, editing clears the error", async () => {
    const onImport = vi.fn<(code: string) => Promise<BuildImportResult>>().mockResolvedValue(invalid);
    render(<BuildImport onImport={onImport} />);
    paste("not-a-pob-code");
    fireEvent.click(screen.getByRole("button", { name: "Import build" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("couldn't be parsed");
    const input = screen.getByLabelText("Path of Building code or XML");
    expect(input).toHaveProperty("value", "not-a-pob-code");
    fireEvent.change(input, { target: { value: "not-a-pob-code-v2" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("non-422 failure (local server unreachable) renders its own alert, not the parse error", async () => {
    const onImport = vi.fn<(code: string) => Promise<BuildImportResult>>().mockResolvedValue(unreachable);
    render(<BuildImport onImport={onImport} />);
    paste("eNq1RealCode");
    fireEvent.click(screen.getByRole("button", { name: "Import build" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("local server");
    expect(alert.textContent).not.toContain("couldn't be parsed");
  });
});

describe("success state", () => {
  it("renders every BuildSummary display field and offers re-import", async () => {
    const onImport = vi.fn<(code: string) => Promise<BuildImportResult>>().mockResolvedValue(ok);
    render(<BuildImport onImport={onImport} />);
    paste("eNq1RealCode");
    fireEvent.click(screen.getByRole("button", { name: "Import build" }));
    await screen.findByRole("status");
    expect(screen.getByText("Build imported")).toBeTruthy();
    expect(screen.getByText("Witch (Occultist)")).toBeTruthy();
    expect(screen.getByText("90")).toBeTruthy();
    expect(screen.getByText("Vortex (inferred)")).toBeTruthy();
    expect(screen.getByText("mapping")).toBeTruthy();
    // Reset returns to the editing state with a cleared paste.
    fireEvent.click(screen.getByRole("button", { name: "Import a different build" }));
    expect(screen.getByLabelText("Path of Building code or XML")).toHaveProperty("value", "");
  });
});
