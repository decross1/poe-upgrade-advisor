import { barFillFraction, barOverflows, deltaTone, formatDelta } from "../lib/verdictFormat";

export interface DeltaBarProps {
  label: string;
  delta: number;
  /** RULING-6: in CANT_EVALUATE the deltas are untrustworthy sentinels —
   *  render an em-dash with an empty track, never the numbers. */
  suppressed?: boolean;
}

/** One delta row: `label — signed bar — numeric value`. The sign in the number
 *  is the accessible carrier of direction; the bar is decorative (aria-hidden). */
export function DeltaBar({ label, delta, suppressed = false }: DeltaBarProps) {
  if (suppressed) {
    return (
      <div className="delta-row delta-row--suppressed">
        <span className="delta-label">{label}</span>
        <span className="delta-track" aria-hidden="true" />
        <span className="delta-value">—</span>
      </div>
    );
  }
  const tone = deltaTone(delta);
  return (
    <div className={`delta-row delta-row--${tone}`}>
      <span className="delta-label">{label}</span>
      <span className="delta-track" aria-hidden="true">
        <span className={`delta-fill delta-fill--${tone}`} style={{ width: `${(barFillFraction(delta) * 100).toFixed(1)}%` }} />
        {barOverflows(delta) && <span className="delta-overflow">»</span>}
      </span>
      <span className="delta-value">{formatDelta(delta)}</span>
    </div>
  );
}
