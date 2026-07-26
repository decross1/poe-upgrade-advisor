import { useEffect, useState } from "react";
import { SessionCard } from "../session/SessionCard";
import { useCardSession } from "../session/useCardSession";
import { BuildImport } from "../components/BuildImport";
import { DetailsPanel } from "../components/DetailsPanel";
import { importBuildViaClient } from "./importBuildClient";
import { loadBreakdownViaClient } from "./detailsClient";

/**
 * Demo harness (npm run mock + npm run dev): every picker entry is a "hotkey
 * press" whose item text routes the TASK-206 fixture mock (web/mock/server.mjs)
 * via its marker convention. The card is whatever the mock returns over real
 * HTTP through the generated client — nothing is inlined.
 *
 *   @fixture:<name>  → contracts/fixtures/<name>.json
 *   @error:404/422   → bare status codes (RULING-20)
 */

function demoItem(label: string, marker: string): string {
  return `Rarity: RARE\n${label}\n--------\n(demo item text; the mock routes on the marker below)\n${marker}`;
}

const DEMO_ITEMS: Record<string, string> = {
  "upgrade_mapping (UPGRADE)": demoItem("Doom Wrap", "@fixture:upgrade_mapping"),
  "sidegrade_bossing (SIDEGRADE)": demoItem("Foe Grip", "@fixture:sidegrade_bossing"),
  "downgrade_mapping (DOWNGRADE)": demoItem("Grief Loop", "@fixture:downgrade_mapping"),
  "cant_evaluate_trigger_build (CAN'T EVALUATE)": demoItem("Storm Coil", "@fixture:cant_evaluate_trigger_build"),
  "upgrade_rich_assumptions_chip (badge + 6 chips)": demoItem("Rich Band", "@fixture:upgrade_rich_assumptions_chip"),
  "sidegrade_balanced_low_confidence (balanced + badge)": demoItem("Even Clasp", "@fixture:sidegrade_balanced_low_confidence"),
  "edge_degraded_minimal (degraded)": demoItem("Bare Sash", "@fixture:edge_degraded_minimal"),
  "error: no active build (404)": demoItem("Doom Wrap", "@error:404"),
  "error: unparseable item (422)": demoItem("???", "@error:422"),
};

export function App() {
  const [itemName, setItemName] = useState<string>(Object.keys(DEMO_ITEMS)[0]);
  const { state, loadingVisible, evaluate, tapChip } = useCardSession();
  const [detailsOpen, setDetailsOpen] = useState(false);

  // Picking an item = one hotkey press = one fresh session (RULING-18).
  useEffect(() => {
    evaluate(DEMO_ITEMS[itemName]);
    setDetailsOpen(false);
  }, [itemName, evaluate]);

  const card = state.card;

  return (
    <main className="harness">
      <h1>Verdict card — live session harness</h1>
      <p className="harness-note">
        Talks to the fixture mock at <code>http://127.0.0.1:47791/api/v0</code> (start it with{" "}
        <code>npm run mock</code>). Tapping a boolean chip issues one real <code>POST /diff</code>{" "}
        with the accumulated overrides (I3; spec §7).
      </p>

      {/* TASK-207: build-import surface, wired to POST /build on the TASK-206
          mock (or the real server — same generated client, same base URL). */}
      <BuildImport onImport={importBuildViaClient} />
      <label className="fixture-picker">
        Hotkey item:{" "}
        <select value={itemName} onChange={(e) => setItemName(e.target.value)}>
          {Object.keys(DEMO_ITEMS).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>

      <SessionCard
        state={state}
        loadingVisible={loadingVisible}
        onTapChip={tapChip}
        detailsHref="#details"
      />

      {/* Details affordance → Tier-2 drivers + Tier-3 raw breakdown (TASK-301).
          cant_evaluate_reasons appear ONLY here, never on the card.
          [RULING-3; PM-REFINEMENT on #25] */}
      {card && (
        <p>
          <a
            href="#details"
            onClick={(e) => {
              e.preventDefault();
              setDetailsOpen((open) => !open);
            }}
          >
            {detailsOpen ? "Hide details" : "Open details (Tier 2/3)"}
          </a>
        </p>
      )}
      {card && detailsOpen && <DetailsPanel card={card} loadBreakdown={loadBreakdownViaClient} />}

      <h2>Session</h2>
      <pre className="payload-preview">
        {JSON.stringify(
          {
            phase: state.phase,
            preset_echo: state.preset ?? null,
            applied_overrides: Object.fromEntries(state.appliedOverrides),
          },
          null,
          2,
        )}
      </pre>
    </main>
  );
}
