/**
 * The shell's render tree: exactly what the overlay window shows for each
 * ShellState. The verdict card itself is the SHARED component from
 * web/src/components (TASK-205) — mounted here, never re-implemented
 * (issue #11: "Do not re-implement the card here — port it").
 *
 * Non-verdict states are NOT VerdictCards (docs/specs/verdict_card.md §8):
 * one short line + at most one affordance, in the same card frame, with the
 * exact §8.2 texts. Chip one-tap re-diff is wired (issue #64): VERDICT and
 * REDIFFING carry the session projection (applied overrides, pending chip,
 * transient message) and taps are forwarded to the main-process flow, which
 * alone decides whether a tap becomes a request (S2).
 */
import { useEffect, useState } from "react";
import { VerdictCard } from "../../../web/src/components/VerdictCard";
import type { Assumption, OverrideEntry } from "../../../web/src/lib/overrides";
import { LOADING_FLASH_GUARD_MS, type ShellState } from "../shellState";

export interface OverlayCardProps {
  state: ShellState;
  /** Forwards a chip tap to the flow (renderer → bridge → main). */
  onChipTap?: (assumption: Assumption) => void;
}

/** Rehydrate the IPC-safe OverrideEntry[] into the Map the card consumes. */
function toOverrideMap(entries: OverrideEntry[]): ReadonlyMap<string, unknown> {
  return new Map(entries.map((e) => [e.assumption_id, e.value]));
}

export function OverlayCard({ state, onChipTap }: OverlayCardProps) {
  // The shared chip computes the would-be overrides payload from RENDERED
  // state; the flow recomputes authoritatively from the session (single
  // source), so only the tapped assumption crosses the boundary.
  const handleOverride = (_overrides: OverrideEntry[], assumption: Assumption) =>
    onChipTap?.(assumption);
  switch (state.kind) {
    case "HIDDEN":
      return null;
    case "LOADING":
      return <LoadingPanel />;
    case "VERDICT":
      return (
        <VerdictCard
          card={state.card}
          appliedOverrides={toOverrideMap(state.appliedOverrides)}
          onOverride={onChipTap ? handleOverride : undefined}
          transientMessage={state.transientMessage}
        />
      );
    case "REDIFFING":
      // §8.3: card stays rendered; tapped chip spins; ALL chips disabled (S2).
      return (
        <VerdictCard
          card={state.card}
          appliedOverrides={toOverrideMap(state.appliedOverrides)}
          onOverride={onChipTap ? handleOverride : undefined}
          chipsDisabled
          pendingChipId={state.pendingChipId}
        />
      );
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
