import { CardStatus } from "../components/CardStatus";
import { VerdictCard } from "../components/VerdictCard";
import type { Assumption } from "../lib/overrides";
import type { SessionState } from "../lib/session";

export interface SessionCardProps {
  state: SessionState;
  /** §8.1: LOADING renders nothing until the 120 ms flash guard elapses. */
  loadingVisible: boolean;
  onTapChip: (assumption: Assumption) => void;
  /** Tier-2 deep link target; defaults to /breakdown/{diff_id}. */
  detailsHref?: string;
  /** ERROR_NO_BUILD affordance target (web-app import). */
  importHref?: string;
}

/**
 * Renders the session state machine (§8.4): HIDDEN/LOADING/VERDICT/REDIFFING
 * and the three error panels. The VerdictCard itself stays pure; this
 * container is the only component that knows sessions exist.
 */
export function SessionCard({ state, loadingVisible, onTapChip, detailsHref, importHref }: SessionCardProps) {
  switch (state.phase.kind) {
    case "idle":
      return null;
    case "loading":
      return loadingVisible ? <CardStatus kind="loading" /> : null;
    case "error":
      return <CardStatus kind={state.phase.error} importHref={importHref} />;
    case "verdict":
    case "rediffing": {
      if (!state.card) return null;
      // §8.3: the existing card stays fully rendered while the tapped chip
      // pends and all chips go non-interactive (S2 double-tap protection).
      const phase = state.phase;
      const rediffing = phase.kind === "rediffing";
      return (
        <VerdictCard
          card={state.card}
          appliedOverrides={state.appliedOverrides}
          chipsDisabled={rediffing}
          pendingChipId={rediffing ? phase.pendingChipId : undefined}
          transientMessage={state.transientMessage}
          onOverride={(_overrides, assumption) => onTapChip(assumption)}
          detailsHref={detailsHref}
        />
      );
    }
  }
}
