import type { OverrideEntry } from "../lib/overrides";
import type { VerdictCard as VerdictCardData } from "../lib/verdictFormat";
import { showLowConfidenceBadge, verdictDisplayText } from "../lib/verdictFormat";
import { AssumptionsChip } from "./AssumptionsChip";
import { DeltaBar } from "./DeltaBar";

export interface VerdictCardProps {
  card: VerdictCardData;
  /** Session overrides for chip styling/toggling. [RULING-17] */
  appliedOverrides?: ReadonlyMap<string, unknown>;
  /** Receives the /diff overrides payload on chip tap (wiring: TASK-206). */
  onOverride?: (overrides: OverrideEntry[]) => void;
  /** Tier-2 deep link target; defaults to /breakdown/{diff_id}. */
  detailsHref?: string;
}

/**
 * Doctrine I2: the card renders EXACTLY five elements — verdict word (with
 * optional low-confidence modifier), two delta bars, one sentence (verbatim,
 * ≤140 chars), the assumptions chip, one "open details" affordance. Nothing
 * else: no preset, no confidence number, no compute_ms, no diff_id, no
 * cant_evaluate_reasons. [RULING-1/2/3/4]
 */
export function VerdictCard({ card, appliedOverrides, onOverride, detailsHref }: VerdictCardProps) {
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

      {/* 3. One explanation sentence, verbatim plain text. */}
      <p className="verdict-sentence">"{card.sentence}"</p>

      {/* 4. The assumptions chip. */}
      <AssumptionsChip assumptions={card.assumptions} appliedOverrides={appliedOverrides} onOverride={onOverride} />

      {/* 5. One "open details" affordance — emphasized under CAN'T EVALUATE (I5). */}
      <footer className="details-row">
        <a className={`details-link${cantEvaluate ? " details-link--emphasized" : ""}`} href={detailsHref ?? `/breakdown/${encodeURIComponent(card.diff_id)}`}>
          Open details ▸
        </a>
      </footer>
    </section>
  );
}
