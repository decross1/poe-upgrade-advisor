import { useEffect, useState } from "react";
import { SessionCard } from "../session/SessionCard";
import { useCardSession, type DiffFn } from "../session/useCardSession";
import { BuildImport, type BuildImportProps } from "../components/BuildImport";
import { DetailsPanel, type LoadBreakdown } from "../components/DetailsPanel";
import { importBuildViaClient } from "./importBuildClient";
import { loadBreakdownViaClient } from "./detailsClient";

/**
 * Demo harness (python3 -m server + npm run dev) — FLIPPED to the real server
 * (TASK-208, issue #36): every picker entry is a "hotkey press" whose item
 * text is evaluated by the REAL PoB engine behind `server/`. The card is
 * whatever the engine returns over real HTTP through the generated client.
 *
 * The golden item text below is byte-identical to
 * engine/tests/fixtures/item.txt (inlined: src/ may not import from engine/,
 * see test/sourceHygiene.test.ts). Against an imported golden build the real
 * engine returns a deterministic verdict for it.
 *
 * The TASK-206 fixture mock (npm run mock) still binds the same contract
 * address and remains the way to demo all four verdict states on demand via
 * its @fixture:/@error: markers, until TASK-202's mock deletion lands.
 */

// Byte-identical to engine/tests/fixtures/item.txt (trailing newline included).
const GOLDEN_ITEM_TEXT = `Rarity: RARE
Spike Candidate
Vaal Spirit Shield
Item Level: 83
Quality: 0
Sockets: B-B-B
LevelReq: 70
Implicits: 1
9% increased Spell Damage
+60 to Intelligence
30% increased Energy Shield
+100 to maximum Life
+1 to Level of all Cold Spell Skill Gems
+11% to all Elemental Resistances
+43% to Cold Resistance
`;

const DEMO_ITEMS: Record<string, string> = {
  "golden item: Spike Candidate (Vaal Spirit Shield)": GOLDEN_ITEM_TEXT,
  "error: unparseable item (honest 422)": "???",
};

export interface AppProps {
  /** Test seam — the demo always uses the generated client's defaults. */
  diffFn?: DiffFn;
  loadBreakdown?: LoadBreakdown;
  onImport?: BuildImportProps["onImport"];
}

export function App({
  diffFn,
  loadBreakdown = loadBreakdownViaClient,
  onImport = importBuildViaClient,
}: AppProps = {}) {
  const [itemName, setItemName] = useState<string>(Object.keys(DEMO_ITEMS)[0]);
  const { state, loadingVisible, evaluate, tapChip } = useCardSession(diffFn);
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
        Talks to the REAL local server at <code>http://127.0.0.1:47791/api/v0</code> (start it from{" "}
        the repo root with <code>python3 -m server</code>). Import a build below first — before an{" "}
        import the server honestly answers 404. Tapping a boolean chip issues one real{" "}
        <code>POST /diff</code> with the accumulated overrides (I3; spec §7). For the fixture-state{" "}
        demo (all four verdicts on demand) run <code>npm run mock</code> instead.
      </p>

      {/* TASK-207: build-import surface, wired to POST /build on the real
          server (or the TASK-206 mock — same generated client, same base URL). */}
      <BuildImport onImport={onImport} />
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

      {/* The CARD's own details affordance opens Tier 2/3 (I7) — there is
          exactly one details control on the page, and it is the card's.
          cant_evaluate_reasons appear ONLY in the panel, never on the card.
          [RULING-3; PM-REFINEMENT on #25] */}
      <SessionCard
        state={state}
        loadingVisible={loadingVisible}
        onTapChip={tapChip}
        detailsHref="#details"
        onOpenDetails={() => setDetailsOpen((open) => !open)}
        detailsOpen={detailsOpen}
      />
      {card && detailsOpen && <DetailsPanel card={card} loadBreakdown={loadBreakdown} />}

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
