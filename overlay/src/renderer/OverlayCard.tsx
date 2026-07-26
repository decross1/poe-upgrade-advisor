/**
 * The shell's render tree: exactly what the overlay window shows for each
 * ShellState. The verdict card itself is the SHARED component from
 * web/src/components (TASK-205) — mounted here, never re-implemented
 * (issue #11: "Do not re-implement the card here — port it").
 *
 * Non-verdict states are NOT VerdictCards (docs/specs/verdict_card.md §8):
 * one short line + at most one affordance, in the same card frame, with the
 * exact §8.2 texts. Chip one-tap re-diff wiring is TASK-204 (#12); chips
 * render here without an override handler until then.
 */
import { useEffect, useState } from "react";
import { VerdictCard } from "../../../web/src/components/VerdictCard";
import { LOADING_FLASH_GUARD_MS, type ShellState } from "../shellState";

export interface OverlayCardProps {
  state: ShellState;
}

export function OverlayCard({ state }: OverlayCardProps) {
  switch (state.kind) {
    case "HIDDEN":
      return null;
    case "LOADING":
      return <LoadingPanel />;
    case "VERDICT":
      return <VerdictCard card={state.card} />;
    case "ERROR_NO_BUILD":
      return (
        <section className="verdict-card overlay-state" aria-label="Advisor status">
          <p className="overlay-state-line">No build imported.</p>
          {/* The state's one affordance (§8.2); opens the web app import page. */}
          <a className="details-link" href="/build">
            Import a build ▸
          </a>
        </section>
      );
    case "ERROR_UNPARSEABLE":
      return (
        <section className="verdict-card overlay-state" aria-label="Advisor status">
          <p className="overlay-state-line">{"Couldn't read that item — copy it in game with Ctrl+C."}</p>
        </section>
      );
    case "ERROR_UNAVAILABLE":
      return (
        <section className="verdict-card overlay-state" aria-label="Advisor status">
          <p className="overlay-state-line">{"Advisor engine isn't running."}</p>
        </section>
      );
  }
}

/** RULING-19: nothing renders for the first 120 ms of LOADING. */
function LoadingPanel() {
  const [pastGuard, setPastGuard] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setPastGuard(true), LOADING_FLASH_GUARD_MS);
    return () => clearTimeout(timer);
  }, []);
  if (!pastGuard) return null;
  return (
    <section className="verdict-card overlay-state" aria-label="Advisor status">
      <p className="overlay-state-line" role="status">
        Evaluating…
      </p>
    </section>
  );
}
