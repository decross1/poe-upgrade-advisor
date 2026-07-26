/**
 * TASK-301 (issue #13) — Tier-2 view: which mods drove the delta, ranked by
 * contribution. Pure render of the contract's Breakdown.drivers (no I/O —
 * sourceHygiene; the network boundary is the generated client).
 *
 * Accessibility mirrors the two-bar delta rule (role priority 4): direction
 * is carried by sign + arrow + number + stat label, never by color alone.
 * An empty drivers list is a first-class state (CAN'T EVALUATE, I5), not an
 * error.
 */
import type { Breakdown } from "../generated/models/Breakdown";

type Driver = Breakdown["drivers"][number];

function formatContribution(pct: number): string {
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "±";
  return `${sign}${Math.abs(pct).toFixed(1)}%`;
}

function arrow(pct: number): string {
  if (pct > 0) return "▲";
  if (pct < 0) return "▼";
  return "◆";
}

export function Tier2Drivers({ drivers }: { drivers: Driver[] }) {
  if (drivers.length === 0) {
    return (
      <section className="tier2-drivers" aria-label="Top stat drivers">
        <h3>What drove this</h3>
        <p className="drivers-empty">
          No drivers — no delta was computed for this verdict.
        </p>
      </section>
    );
  }
  const max = Math.max(...drivers.map((d) => Math.abs(d.contribution_pct)), 0.1);
  return (
    <section className="tier2-drivers" aria-label="Top stat drivers">
      <h3>What drove this</h3>
      <table>
        <thead>
          <tr>
            <th scope="col">Mod</th>
            <th scope="col">Stat</th>
            <th scope="col">Contribution</th>
          </tr>
        </thead>
        <tbody>
          {drivers.map((d, i) => (
            <tr key={i}>
              <td>{d.mod_text}</td>
              <td>
                <code>{d.stat}</code>
              </td>
              <td>
                <span
                  className={`driver-contribution driver-contribution--${
                    d.contribution_pct > 0 ? "positive" : d.contribution_pct < 0 ? "negative" : "neutral"
                  }`}
                >
                  <span aria-hidden="true">{arrow(d.contribution_pct)} </span>
                  {formatContribution(d.contribution_pct)}
                </span>
                <span className="delta-track driver-track" aria-hidden="true">
                  <span
                    className={`delta-fill ${
                      d.contribution_pct > 0
                        ? "delta-fill--positive"
                        : d.contribution_pct < 0
                          ? "delta-fill--negative"
                          : "delta-fill--neutral"
                    }`}
                    style={{ width: `${(Math.abs(d.contribution_pct) / max) * 100}%` }}
                  />
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
