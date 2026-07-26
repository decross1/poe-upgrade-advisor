import { useMemo, useState } from "react";
import type { VerdictCard as VerdictCardData } from "../lib/verdictFormat";
import type { OverrideEntry } from "../lib/overrides";
import { VerdictCard } from "../components/VerdictCard";
import { BuildImport } from "../components/BuildImport";
import { importBuildViaClient } from "./importBuildClient";

// Fixture-driven harness: the card is built entirely from contracts/fixtures/
// (read-only, PM-owned) plus FE-local fixtures for cases with no golden
// fixture yet (docs/specs/verdict_card.md §9 gap note).
import upgradeMappingJson from "../../../contracts/fixtures/upgrade_mapping.json";
import sidegradeBossingJson from "../../../contracts/fixtures/sidegrade_bossing.json";
import downgradeMappingJson from "../../../contracts/fixtures/downgrade_mapping.json";
import cantEvaluateTriggerJson from "../../../contracts/fixtures/cant_evaluate_trigger_build.json";
import upgradeRichChipJson from "../../../contracts/fixtures/upgrade_rich_assumptions_chip.json";
import sidegradeBalancedJson from "../../../contracts/fixtures/sidegrade_balanced_low_confidence.json";
import edgeDegradedJson from "../../../contracts/fixtures/edge_degraded_minimal.json";
import localBarOverflowJson from "../../test/fixtures/local_bar_overflow.json";

// JSON imports widen to string/boolean; the suite proves schema conformance
// (web/test/fixtures.test.ts), so bind to the generated contract types here.
const upgradeMapping = upgradeMappingJson as VerdictCardData;
const sidegradeBossing = sidegradeBossingJson as VerdictCardData;
const downgradeMapping = downgradeMappingJson as VerdictCardData;
const cantEvaluateTrigger = cantEvaluateTriggerJson as VerdictCardData;
const upgradeRichChip = upgradeRichChipJson as VerdictCardData;
const sidegradeBalanced = sidegradeBalancedJson as VerdictCardData;
const edgeDegraded = edgeDegradedJson as VerdictCardData;
const localBarOverflow = localBarOverflowJson as VerdictCardData;

const FIXTURES: Record<string, VerdictCardData> = {
  "upgrade_mapping (UPGRADE)": upgradeMapping,
  "sidegrade_bossing (SIDEGRADE)": sidegradeBossing,
  "downgrade_mapping (DOWNGRADE)": downgradeMapping,
  "cant_evaluate_trigger_build (CAN'T EVALUATE)": cantEvaluateTrigger,
  "upgrade_rich_assumptions_chip (badge + 6 chips)": upgradeRichChip,
  "sidegrade_balanced_low_confidence (balanced + badge)": sidegradeBalanced,
  "edge_degraded_minimal (degraded)": edgeDegraded,
  "local_bar_overflow (local: >25pp + 40-char label)": localBarOverflow,
};

export function App() {
  const [fixtureName, setFixtureName] = useState<string>(Object.keys(FIXTURES)[0]);
  const card = FIXTURES[fixtureName];
  // One "hotkey press = one session": overrides accumulate per item and are
  // cleared when the fixture (item) changes. [RULING-17/18]
  const [appliedOverrides, setAppliedOverrides] = useState<ReadonlyMap<string, unknown>>(new Map());
  const [lastPayload, setLastPayload] = useState<OverrideEntry[] | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const selectFixture = (name: string) => {
    setFixtureName(name);
    setAppliedOverrides(new Map());
    setLastPayload(null);
    setDetailsOpen(false);
  };

  const payloadPreview = useMemo(
    () =>
      JSON.stringify(
        { item_text: "<clipboard item text>", overrides: lastPayload ?? [] },
        null,
        2,
      ),
    [lastPayload],
  );

  return (
    <main className="harness">
      <h1>Verdict card — fixture harness</h1>

      {/* TASK-207: build-import surface, wired to POST /build on the TASK-206
          mock (or the real server — same generated client, same base URL). */}
      <BuildImport onImport={importBuildViaClient} />
      <label className="fixture-picker">
        Fixture:{" "}
        <select value={fixtureName} onChange={(e) => selectFixture(e.target.value)}>
          {Object.keys(FIXTURES).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>

      <VerdictCard
        card={card}
        appliedOverrides={appliedOverrides}
        onOverride={(payload) => {
          // TASK-206 wires this to POST /api/v0/diff; for now we hold the
          // payload and show exactly what would be sent (one tap = one request).
          setLastPayload(payload);
          setAppliedOverrides(new Map(payload.map((o) => [o.assumption_id, o.value])));
        }}
        detailsHref="#details"
      />

      {/* Details affordance → Tier-2 preview. cant_evaluate_reasons appear ONLY
          here, never on the card. [RULING-3; PM-REFINEMENT on #25] */}
      <p>
        <a
          href="#details"
          onClick={(e) => {
            e.preventDefault();
            setDetailsOpen((open) => !open);
          }}
        >
          {detailsOpen ? "Hide details" : "Open details (Tier-2 preview)"}
        </a>
      </p>
      {detailsOpen && (
        <section className="details-panel" aria-label="Details">
          <h2>Details (diff {card.diff_id})</h2>
          {card.cant_evaluate_reasons && card.cant_evaluate_reasons.length > 0 ? (
            <ul>
              {card.cant_evaluate_reasons.map((reason, i) => (
                <li key={i}>{reason}</li>
              ))}
            </ul>
          ) : (
            <p>No can't-evaluate reasons for this verdict.</p>
          )}
        </section>
      )}

      <h2>Last override payload (would be POSTed to /api/v0/diff)</h2>
      <pre className="payload-preview">{payloadPreview}</pre>
    </main>
  );
}
