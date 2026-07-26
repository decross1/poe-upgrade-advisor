/**
 * TASK-301 (issue #13) — the details affordance's panel: Tier-2 drivers +
 * Tier-3 raw breakdown behind the card's one "open details" tap (I7).
 *
 * Data comes from GET /breakdown/{diff_id} — the contract's Tier-2/3 surface,
 * keyed by the diff_id of the /diff response already on screen. One panel
 * open = one request (the tap is the explicit user action; no polling, no
 * preloading). cant_evaluate_reasons stay here and ONLY here (RULING-3).
 *
 * The component does no network I/O itself (sourceHygiene): `loadBreakdown`
 * is injected; the demo wires it to the generated client.
 */
import { useEffect, useRef, useState } from "react";
import type { Breakdown } from "../generated/models/Breakdown";
import type { VerdictCard } from "../lib/verdictFormat";
import { Tier2Drivers } from "./Tier2Drivers";
import { Tier3Breakdown } from "./Tier3Breakdown";

export type LoadBreakdown = (diffId: string) => Promise<Breakdown>;

type PanelState =
  | { phase: "loading" }
  | { phase: "error"; status: number }
  | { phase: "loaded"; breakdown: Breakdown };

export function DetailsPanel({
  card,
  loadBreakdown,
}: {
  card: VerdictCard;
  loadBreakdown: LoadBreakdown;
}) {
  const [panel, setPanel] = useState<PanelState>({ phase: "loading" });
  const seqRef = useRef(0);

  // A new card (new hotkey press or chip re-diff) invalidates any in-flight
  // request and re-loads for the new diff_id.
  useEffect(() => {
    const seq = ++seqRef.current;
    setPanel({ phase: "loading" });
    loadBreakdown(card.diff_id)
      .then((breakdown) => {
        if (seq === seqRef.current) setPanel({ phase: "loaded", breakdown });
      })
      .catch((error: unknown) => {
        if (seq !== seqRef.current) return;
        const status = (error as { status?: unknown } | null)?.status;
        setPanel({ phase: "error", status: typeof status === "number" ? status : 0 });
      });
  }, [card.diff_id, loadBreakdown]);

  return (
    <section className="details-panel" aria-label="Details">
      {/* Single text node: split JSX text leaves trailing-whitespace nodes
          in the serialized snapshot. Rendered text is unchanged. */}
      <h2>{`Details (diff ${card.diff_id})`}</h2>
      {card.cant_evaluate_reasons && card.cant_evaluate_reasons.length > 0 && (
        <ul>
          {card.cant_evaluate_reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      )}
      {panel.phase === "loading" && <p role="status">Loading breakdown…</p>}
      {panel.phase === "error" && (
        <p role="alert">
          {panel.status === 404
            ? "Breakdown expired or unknown for this diff."
            : "Breakdown unavailable — the server could not be reached."}
        </p>
      )}
      {panel.phase === "loaded" && (
        <>
          <Tier2Drivers drivers={panel.breakdown.drivers} />
          <Tier3Breakdown tree={panel.breakdown.pob_breakdown} />
        </>
      )}
    </section>
  );
}
