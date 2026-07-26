import type { Assumption, OverrideEntry } from "../lib/overrides";
import { isTappable, toggleOverride } from "../lib/overrides";

export interface AssumptionsChipProps {
  assumptions: Assumption[];
  /** Session overrides (assumption_id → overridden value). [RULING-17] */
  appliedOverrides?: ReadonlyMap<string, unknown>;
  /** Called with the FULL accumulated overrides payload on each tap. */
  onOverride?: (overrides: OverrideEntry[]) => void;
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
export function AssumptionsChip({ assumptions, appliedOverrides, onOverride }: AssumptionsChipProps) {
  const applied = appliedOverrides ?? new Map<string, unknown>();
  return (
    <div className="chip-strip" role="group" aria-label="Assumptions">
      {assumptions.map((a) => {
        const overridden = applied.has(a.id);
        const className = [
          "chip",
          a.impactful ? "" : "chip--dimmed",
          overridden ? "chip--overridden" : "",
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
            onClick={() => onOverride?.(toggleOverride(applied, a))}
          >
            {content}
          </button>
        ) : (
          // Non-boolean: display-only in MVP, no press affordance. [RULING-14]
          <span key={a.id} className={className}>
            {content}
          </span>
        );
      })}
    </div>
  );
}
