import { useCallback, useState } from "react";
import { SessionCard } from "../session/SessionCard";
import { useCardSession, type DiffFn } from "../session/useCardSession";
import { BuildImport, type BuildImportProps } from "../components/BuildImport";
import { DetailsPanel, type LoadBreakdown } from "../components/DetailsPanel";
import { ItemInput } from "../components/ItemInput";
import { importBuildViaClient } from "./importBuildClient";
import { loadBreakdownViaClient } from "./detailsClient";

/**
 * Demo harness (python3 -m server + npm run dev) — FLIPPED to the real server
 * (TASK-208, issue #36) and now the PLAYER's surface (TASK-211-S1, issue
 * #90): the paste box is the item path. The player pastes their own in-game
 * Ctrl+C item text and submits; the card is whatever the REAL PoB engine
 * behind `server/` returns over real HTTP through the generated client.
 *
 * The page starts with an empty box and NO card and issues NO request until
 * the player submits (S2: one explicit submit = exactly one POST /diff). The
 * paste box feeds the same useCardSession evaluate() a hotkey press would —
 * the session machine, the card, and the generated client are untouched.
 *
 * The TASK-206 fixture mock (npm run mock) still binds the same contract
 * address and remains the way to demo all four verdict states on demand via
 * its @fixture:/@error: markers, until TASK-202's mock deletion lands.
 */

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
  const { state, loadingVisible, evaluate, tapChip } = useCardSession(diffFn);
  const [detailsOpen, setDetailsOpen] = useState(false);

  // One explicit submit = one hotkey press = one fresh session (RULING-18).
  // No request leaves this page until the player submits (S2).
  const onEvaluate = useCallback(
    (itemText: string) => {
      setDetailsOpen(false);
      evaluate(itemText);
    },
    [evaluate],
  );

  const card = state.card;

  return (
    <main className="harness">
      <h1>Verdict card — live session harness</h1>
      <p className="harness-note">
        Talks to the REAL local server at <code>http://127.0.0.1:47791/api/v0</code> (start it from{" "}
        the repo root with <code>python3 -m server</code>). Import your build once below — before an{" "}
        import the server honestly answers 404 — then copy an item in game with <code>Ctrl+C</code>{" "}
        and paste it anywhere on this page (<code>Ctrl+V</code>) to evaluate it. One explicit submit{" "}
        = exactly one <code>POST /diff</code> (S2); tapping a boolean chip issues one real re-diff{" "}
        with the accumulated overrides (I3; spec §7). For the fixture-state demo (all four verdicts{" "}
        on demand) run <code>npm run mock</code> instead.
      </p>

      {/* TASK-207: build-import surface, wired to POST /build on the real
          server (or the TASK-206 mock — same generated client, same base URL). */}
      <BuildImport onImport={onImport} />

      {/* TASK-211-S1 (issue #90): the paste box is THE item path — the player
          evaluates their own item, never a fixture picker. */}
      <ItemInput onEvaluate={onEvaluate} />

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
