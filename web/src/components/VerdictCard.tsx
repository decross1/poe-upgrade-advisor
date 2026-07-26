import type { Assumption, OverrideEntry } from "../lib/overrides";
import type { VerdictCard as VerdictCardData } from "../lib/verdictFormat";
import { showLowConfidenceBadge, verdictDisplayText } from "../lib/verdictFormat";
import { AssumptionsChip } from "./AssumptionsChip";
import { DeltaBar } from "./DeltaBar";

export interface VerdictCardProps {
  card: VerdictCardData;
  /** Session overrides for chip styling/toggling. [RULING-17] */
  appliedOverrides?: ReadonlyMap<string, unknown>;
  /** Receives the /diff overrides payload + tapped chip on chip tap. */
  onOverride?: (overrides: OverrideEntry[], assumption: Assumption) => void;
  /** §8.3 REDIFFING: every chip non-interactive until resolution (S2). */
  chipsDisabled?: boolean;
  /** §8.3 REDIFFING: this chip shows the inline spinner. */
  pendingChipId?: string;
  /** §8.3 [RULING-21]: transient replacement for the sentence slot. */
  transientMessage?: string | null;
  /** Tier-2 deep link target; defaults to /breakdown/{diff_id}. */
  detailsHref?: string;
  /** When set, the details tap opens Tier 2 in place (I7) and navigation is
   *  suppressed; href remains the no-JS/deep-link fallback. */
  onOpenDetails?: () => void;
  /** Panel state reflected on the affordance (only with onOpenDetails). */
  detailsOpen?: boolean;
}

/**
 * Doctrine I2: the card renders EXACTLY five elements — verdict word (with
 * optional low-confidence modifier), two delta bars, one sentence (verbatim,
 * ≤140 chars), the assumptions chip, one "open details" affordance. Nothing
 * else: no preset, no confidence number, no compute_ms, no diff_id, no
 * cant_evaluate_reasons. [RULING-1/2/3/4]
 */
export function VerdictCard({ card, appliedOverrides, onOverride, chipsDisabled, pendingChipId, transientMessage, detailsHref, onOpenDetails, detailsOpen }: VerdictCardProps) {
  const cantEvaluate = card.verdict === "CANT_EVALUATE";
  const verdictKey = card.verdict.toLowerCase();
  return (
    <section className={`verdict-card verdict-card--${verdictKey}`} aria-label="Upgrade verdict">
      {/* 1. Verdict word (+ low-confidence modifier — part of this element, RULING-7) */}
      <header className="verdict-header">
        <span className={`verdict-word verdict-word--${verdictKey}`}>{verdictDisplayText(card.verdict)}</span>
        {showLowConfidenceBadge(card) && <span className="low-confidence-badge">◦ low confidence</span>}
      </header>

      {/* 2. Two deltas: offense, defense — fixed order, never a third row. */}
      <div className="delta-bars">
        <DeltaBar label="Offense" delta={card.offense_delta_pct} suppressed={cantEvaluate} />
        <DeltaBar label="Defense" delta={card.defense_delta_pct} suppressed={cantEvaluate} />
      </div>

      {/* 3. One explanation sentence, verbatim plain text. The re-diff
          failure message REUSES this slot, keeping I2's element count
          intact (§8.3, RULING-21). */}
      {transientMessage ? (
        <p className="verdict-sentence verdict-sentence--transient">{transientMessage}</p>
      ) : (
        <p className="verdict-sentence">"{card.sentence}"</p>
      )}

      {/* 4. The assumptions chip. */}
      <AssumptionsChip
        assumptions={card.assumptions}
        appliedOverrides={appliedOverrides}
        onOverride={onOverride}
        disabled={chipsDisabled}
        pendingChipId={pendingChipId}
      />

      {/* 5. One "open details" affordance — emphasized under CAN'T EVALUATE (I5).
          This is THE details affordance (I7): with onOpenDetails wired it opens
          Tier 2 itself; no second control may duplicate it. */}
      <footer className="details-row">
        <a
          className={`details-link${cantEvaluate ? " details-link--emphasized" : ""}`}
          href={detailsHref ?? `/breakdown/${encodeURIComponent(card.diff_id)}`}
          aria-expanded={onOpenDetails ? (detailsOpen ?? false) : undefined}
          onClick={
            onOpenDetails
              ? (e) => {
                  e.preventDefault();
                  onOpenDetails();
                }
              : undefined
          }
        >
          {onOpenDetails && detailsOpen ? "Hide details ▾" : "Open details ▸"}
        </a>
      </footer>
    </section>
  );
}
