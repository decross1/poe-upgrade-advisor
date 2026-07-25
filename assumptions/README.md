# Assumptions Engine

The product's moat: PoB-grade config, inferred, so users never see a settings maze.
Everything here is **data**. The evaluator (owned by Backend, lives in `server/`)
loads these files; changing behavior means changing YAML + fixtures, which is why
this component is safe for autonomous maintenance (Doctrine I8).

- `rules/` — inference rules. Each rule: stable `id`, `when` (build predicates),
  `set` (PoB config keys), `confidence_weight`, `chip_label` (≤40 chars, shown to user).
- `presets/` — ≤3 scenario bundles (Doctrine I4) of concrete PoB config values.
- `fixtures/` — build → expected assumptions. Every Discord "it guessed wrong"
  report becomes a fixture BEFORE its fix merges. CI: `scripts/check_fixture_coverage.py`.

NOTE for Backend: PoB config key names below are indicative; verify exact
`Input`/config names against the vendored PoB source during TASK-101 and correct
these files in the same PR (fixtures keep you honest).
