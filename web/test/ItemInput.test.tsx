/**
 * TASK-211-S1 (issue #90) — the item paste box contract:
 *
 *  - AC-2: an explicit submit calls onEvaluate exactly once with the EXACT
 *    pasted text; an empty or whitespace-only box issues NO call; typing
 *    without submitting issues NO call (S2 — one server action per explicit
 *    user action; no evaluate-on-keystroke).
 *  - AC-3: a paste event outside any text field routes the text into the box
 *    and submits it exactly once; a paste INSIDE a text field keeps its
 *    native behavior (no routing, no extra submit).
 *
 * The component does no network I/O — onEvaluate is the injected seam.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ItemInput } from "../src/components/ItemInput";

// Representative in-game Ctrl+C text (exact string must round-trip verbatim).
const ITEM_TEXT = `Rarity: RARE
Spike Candidate
Vaal Spirit Shield
Item Level: 83
+100 to maximum Life
`;

function pasteOutside(text: string) {
  const event = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", {
    value: { getData: () => text },
  });
  fireEvent(document.body, event);
}

describe("ItemInput (TASK-211-S1, issue #90)", () => {
  it("starts with an empty box and a disabled submit", () => {
    render(<ItemInput onEvaluate={vi.fn()} />);
    expect((screen.getByLabelText(/Item text/) as HTMLTextAreaElement).value).toBe("");
    expect(
      (screen.getByRole("button", { name: "Evaluate item" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("submitting calls onEvaluate exactly once with the exact pasted text", () => {
    const onEvaluate = vi.fn();
    render(<ItemInput onEvaluate={onEvaluate} />);
    fireEvent.change(screen.getByLabelText(/Item text/), {
      target: { value: ITEM_TEXT },
    });
    fireEvent.click(screen.getByRole("button", { name: "Evaluate item" }));
    expect(onEvaluate).toHaveBeenCalledTimes(1);
    expect(onEvaluate).toHaveBeenCalledWith(ITEM_TEXT);
  });

  it("an empty or whitespace-only box issues NO call", () => {
    const onEvaluate = vi.fn();
    render(<ItemInput onEvaluate={onEvaluate} />);
    const button = screen.getByRole("button", { name: "Evaluate item" });

    // Empty: the control is disabled, and even a synthetic submit is a no-op.
    fireEvent.click(button);
    expect(onEvaluate).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Item text/), {
      target: { value: "  \n\t " },
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(onEvaluate).not.toHaveBeenCalled();
  });

  it("typing without submitting issues NO call", () => {
    const onEvaluate = vi.fn();
    render(<ItemInput onEvaluate={onEvaluate} />);
    fireEvent.change(screen.getByLabelText(/Item text/), {
      target: { value: ITEM_TEXT },
    });
    expect(onEvaluate).not.toHaveBeenCalled();
  });

  it("Ctrl+V outside any text field routes the text into the box and submits exactly once", () => {
    const onEvaluate = vi.fn();
    render(<ItemInput onEvaluate={onEvaluate} />);
    pasteOutside(ITEM_TEXT);
    expect(onEvaluate).toHaveBeenCalledTimes(1);
    expect(onEvaluate).toHaveBeenCalledWith(ITEM_TEXT);
    // The routed text is visible in the box — the player sees what was sent.
    expect((screen.getByLabelText(/Item text/) as HTMLTextAreaElement).value).toBe(ITEM_TEXT);
  });

  it("a whitespace-only page paste routes nothing and submits nothing", () => {
    const onEvaluate = vi.fn();
    render(<ItemInput onEvaluate={onEvaluate} />);
    pasteOutside("   ");
    expect(onEvaluate).not.toHaveBeenCalled();
    expect((screen.getByLabelText(/Item text/) as HTMLTextAreaElement).value).toBe("");
  });

  it("a paste INSIDE a text field is left to the field (no routing, no submit)", () => {
    const onEvaluate = vi.fn();
    render(<ItemInput onEvaluate={onEvaluate} />);
    const box = screen.getByLabelText(/Item text/);
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: { getData: () => ITEM_TEXT },
    });
    fireEvent(box, event);
    expect(onEvaluate).not.toHaveBeenCalled();
  });
});
