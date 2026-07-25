# web/ — Tier-2/3 profile UI (Owner: Frontend)

React + generated API client from `contracts/openapi.yaml` (never hand-rolled).
Tier 2: delta drivers view (Breakdown.drivers). Tier 3: full PoB breakdown,
stash scan (POST /scan) ranked results, tree planner ("best next 5 points" —
engine exposes PoB's node power ratings), and the ONLY place user configuration
may live. Overrides set here become sticky build state server-side.
