import { useEffect, useState } from "react";
import type { FormEvent } from "react";

/**
 * TASK-211-S1 (issue #90) — the item paste box, the PRIMARY way a player
 * evaluates THEIR OWN item: paste in-game Ctrl+C text → one explicit submit →
 * exactly one evaluation. S2: one server action per explicit user action —
 * nothing on keystroke, no debounce-fired request, no request on an empty or
 * whitespace-only box.
 *
 * Page-level Ctrl+V: a paste event anywhere on the page that is NOT already
 * inside a text field is routed into the box and submitted, so the
 * pre-overlay flow stays one keypress (issue #90 AC-3).
 *
 * Doctrine: I1 — a paste box is an input surface, not a settings surface;
 * there are no options here. I5 — the client never pre-judges item text;
 * unreadable text is submitted and the server's honest answer (including a
 * 422) is what renders.
 *
 * Portability contract (web/test/sourceHygiene.test.ts): this component does
 * NO network I/O. The caller injects the card session's evaluate() as
 * `onEvaluate` — the same one the demo picker fed (TASK-208).
 */

export interface ItemInputProps {
  /** Called exactly once per explicit submit with the exact pasted text. */
  onEvaluate: (itemText: string) => void;
}

/** Paste targets that keep their native behavior (any text field). */
function isTextField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === "TEXTAREA" ||
    target.tagName === "INPUT" ||
    target.isContentEditable
  );
}

export function ItemInput({ onEvaluate }: ItemInputProps) {
  const [itemText, setItemText] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (itemText.trim() === "") return; // S2: no request on an empty box
    onEvaluate(itemText); // the exact pasted text — never pre-judged (I5)
  };

  // Ctrl+V outside any text field = fill the box and submit it (one press).
  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      if (isTextField(event.target)) return;
      const text = event.clipboardData?.getData("text") ?? "";
      if (text.trim() === "") return;
      event.preventDefault();
      setItemText(text);
      onEvaluate(text);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [onEvaluate]);

  return (
    <section className="item-input" aria-label="Evaluate an item">
      <h2>Evaluate an item</h2>
      <form onSubmit={submit}>
        <label className="item-input-label" htmlFor="item-text-input">
          Item text (Ctrl+C in game, then Ctrl+V here)
        </label>
        <textarea
          id="item-text-input"
          className="item-input-box"
          rows={8}
          value={itemText}
          placeholder="Paste your item here"
          onChange={(e) => setItemText(e.target.value)}
        />
        <button
          type="submit"
          className="item-input-submit"
          disabled={itemText.trim() === ""}
        >
          Evaluate item
        </button>
      </form>
    </section>
  );
}
