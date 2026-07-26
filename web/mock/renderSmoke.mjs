// TASK-206 wire smoke render — NOT the product verdict card (TASK-205 owns
// that). This exists so a test can "render" a VerdictCard that arrived over
// the wire through the generated client, proving the payload is displayable.
// Mirrors contracts/fixtures/README.md convention 9 (display text),
// docs/specs/verdict_card.md RULING-6 (bar suppression on CANT_EVALUATE),
// RULING-9 (near-zero renders "0.0%" unsigned), RULING-5 (percent points).

const VERDICT_WORDS = {
  UPGRADE: 'UPGRADE',
  SIDEGRADE: 'SIDEGRADE',
  DOWNGRADE: 'DOWNGRADE',
  CANT_EVALUATE: "CAN'T EVALUATE", // fixtures README convention 9
};

function formatDelta(pct) {
  if (Math.abs(pct) < 0.05) return '0.0%'; // RULING-9: unsigned, neutral
  return `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`;
}

export function renderSmokeCard(card) {
  const cantEvaluate = card.verdict === 'CANT_EVALUATE';
  return {
    word: VERDICT_WORDS[card.verdict],
    // RULING-6: deltas are untrustworthy sentinels here — never shown.
    offense: cantEvaluate ? '—' : formatDelta(card.offense_delta_pct),
    defense: cantEvaluate ? '—' : formatDelta(card.defense_delta_pct),
    sentence: card.sentence,
    chips: card.assumptions.map((a) => a.label),
    diffId: card.diff_id,
  };
}
