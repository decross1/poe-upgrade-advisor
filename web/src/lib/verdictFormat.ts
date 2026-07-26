/**
 * Pure presentation rules for the verdict card. Everything here traces to a
 * numbered ruling in docs/specs/verdict_card.md — do not add behavior that the
 * spec does not define.
 */
import type { components } from "./api-types";

export type VerdictCard = components["schemas"]["VerdictCard"];
export type Verdict = VerdictCard["verdict"];

/** Mirror of assumptions/rules/confidence.yaml: low_confidence_badge_below.
 *  If that file changes, this constant must change with it (checked in review).
 *  [RULING-8, spec §4] */
export const LOW_CONFIDENCE_BADGE_BELOW = 0.75;

/** RULING-10: bar full scale is 25 percentage points. */
export const BAR_FULL_SCALE_PP = 25;

/** RULING-9: |delta| below this renders unsigned, neutral, empty bar. */
export const NEAR_ZERO_THRESHOLD_PP = 0.05;

/** U+2212 minus, picked once and locked by snapshots (spec §5). */
export const MINUS_SIGN = "−";

/** "+12.4%", "−1.8%", "0.0%" — explicit sign, one decimal, % suffix. [RULING-9] */
export function formatDelta(delta: number): string {
  if (Math.abs(delta) < NEAR_ZERO_THRESHOLD_PP) return "0.0%";
  const sign = delta > 0 ? "+" : MINUS_SIGN;
  return `${sign}${Math.abs(delta).toFixed(1)}%`;
}

/** clamp(|delta| / 25, 0, 1). [RULING-10] */
export function barFillFraction(delta: number): number {
  return Math.min(Math.abs(delta) / BAR_FULL_SCALE_PP, 1);
}

/** |delta| > 25 → full bar plus overflow chevron. [RULING-10] */
export function barOverflows(delta: number): boolean {
  return Math.abs(delta) > BAR_FULL_SCALE_PP;
}

export type DeltaTone = "positive" | "negative" | "neutral";

/** Color tone per bar, independently (positive is always better). [RULING-5] */
export function deltaTone(delta: number): DeltaTone {
  if (Math.abs(delta) < NEAR_ZERO_THRESHOLD_PP) return "neutral";
  return delta > 0 ? "positive" : "negative";
}

/** CANT_EVALUATE is wire format only; I2's exact wording has the apostrophe. */
export function verdictDisplayText(verdict: Verdict): string {
  return verdict === "CANT_EVALUATE" ? "CAN'T EVALUATE" : verdict;
}

/** Modifier on the verdict word only — never a numeric confidence (RULING-2/7/8). */
export function showLowConfidenceBadge(card: VerdictCard): boolean {
  return card.verdict !== "CANT_EVALUATE" && card.confidence < LOW_CONFIDENCE_BADGE_BELOW;
}
