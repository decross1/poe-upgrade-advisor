# overlay/ — Verdict card overlay (Owner: Frontend)

Tauri preferred (small footprint helps I6); decide via ADR in TASK-201.
Flow: global hotkey → read clipboard (populated by the game's own Ctrl+C) →
canonicalize item text → POST /diff → render VerdictCard (Tier 1) →
tap assumption chip = one re-diff with override → "details" deep-links web/.

Hard rules: no settings surface (I1, CI-checked); render ≤50 ms after response;
clipboard is the ONLY game input (S1); never synthesize input (S2);
windowed-fullscreen compatible, always-on-top, hide when game loses focus.
Snapshot-test all four verdict states including CANT_EVALUATE.
