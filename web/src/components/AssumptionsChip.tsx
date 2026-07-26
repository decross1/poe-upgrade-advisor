import type { Assumption, OverrideEntry } from "../lib/overrides";
import { isTappable, toggleOverride } from "../lib/overrides";

export interface AssumptionsChipProps {
  assumptions: Assumption[];
  /** Session overrides (assumption_id → overridden value). [RULING-17] */
  appliedOverrides?: ReadonlyMap<string, unknown>;
  /** Called with the FULL accumulated overrides payload plus the tapped chip. */
  onOverride?: (overrides: OverrideEntry[], assumption: Assumption) => void;
  /** §8.3: ALL chips non-interactive while a re-diff is in flight (S2). */
  disabled?: boolean;
  /** §8.3: the tapped chip shows an inline spinner replacing its label. */
  pendingChipId?: string;
}

/**
 * The assumptions chip (I2, singular) as ONE card element: a strip of up to 6
 * chips rendered verbatim in server order — no sorting, filtering, truncation,
 * or overflow menu (I3 "no hidden assumptions"). [RULING-11]
 *
 * - Chip text is Assumption.label verbatim; Assumption.value is NEVER rendered. [RULING-12/13]
 * - impactful:false chips dim but stay visible AND flippable. (fixtures README conv. 6)
 * - Only boolean-valued chips are tappable. [RULING-14/15]
 */
export function AssumptionsChip({ assumptions, appliedOverrides, onOverride, disabled, pendingChipId }: AssumptionsChipProps) {
  const applied = appliedOverrides ?? new Map<string, unknown>();
  return (
    <div className="chip-strip" role="group" aria-label="Assumptions" aria-busy={disabled ? true : undefined}>
      {assumptions.map((a) => {
        const overridden = applied.has(a.id);
        const pending = pendingChipId === a.id;
        const className = [
          "chip",
          a.impactful ? "" : "chip--dimmed",
          overridden ? "chip--overridden" : "",
          pending ? "chip--pending" : "",
        ]
          .filter(Boolean)
          .join(" ");
        const content = (
          <>
            {overridden && (
              <span className="chip-revert" aria-hidden="true">
                ↺{" "}
              </span>
            )}
            {a.label}
          </>
        );
        return isTappable(a) ? (
          <button
            key={a.id}
            type="button"
            className={className}
            disabled={disabled}
            // The spinner replaces the visible label; keep the chip's name.
            aria-label={pending ? a.label : undefined}
            aria-busy={pending ? true : undefined}
            onClick={() => onOverride?.(toggleOverride(applied, a), a)}
          >
            {pending ? (
              <span className="chip-spinner" aria-hidden="true" />
            ) : (
              content
            )}
          </button>
        ) : (
          // Non-boolean: display-only in MVP, no press affordance. [RULING-14]
          <span key={a.id} className={className} aria-disabled={disabled ? true : undefined}>
            {pending ? (
              <span className="chip-spinner" aria-hidden="true" />
            ) : (
              content
            )}
          </span>
        );
      })}
    </div>
  );
}
