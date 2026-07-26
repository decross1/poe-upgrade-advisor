# overlay/ — Verdict card overlay (Owner: Frontend)

Tauri preferred (small footprint helps I6); decide via ADR in TASK-201.
Flow: global hotkey → read clipboard (populated by the game's own Ctrl+C) →
canonicalize item text → POST /diff → render VerdictCard (Tier 1) →
tap assumption chip = one re-diff with override → "details" deep-links web/.

Hard rules: no settings surface (I1, CI-checked); render ≤50 ms after response;
clipboard is the ONLY game input (S1); never synthesize input (S2);
windowed-fullscreen compatible, always-on-top, hide when game loses focus.
Snapshot-test all four verdict states including CANT_EVALUATE.

## Shell (TASK-203, ADR-0004 Electron fallback)

`src/` is the production shell scaffold. The card UI is the shared component
from `web/src/components` (TASK-205) — mounted, never re-implemented — and
`POST /diff` goes through the generated client (`web/src/generated`) only.

- `src/main.ts` — thin electron wiring; all logic lives in the injected,
  headless-tested modules (`diffFlow`, `diffRequest`, `serverEndpoint`).
- `src/diffFlow.ts` — hotkey → clipboard → /diff → state machine (spec §8.4:
  HIDDEN/LOADING/VERDICT/ERROR_*; RULING-19 3000 ms timeout; RULING-20
  status-code-only errors; a newer keypress supersedes an in-flight request).
- `src/serverEndpoint.ts` — backend swap is config-only: the client targets
  `servers[0].url` from `contracts/openapi.yaml` (`http://127.0.0.1:47791/api/v0`,
  the TASK-206 fixture mock today) unless `POE_ADVISOR_SERVER_URL` is set.
  `POE_ADVISOR_WEB_URL` likewise overrides the web-app deep-link base.
- `src/window.ts` / `src/hotkey.ts` / `src/clipboardText.ts` — electron
  adapters: fixed 340 px frameless always-on-top window, one fixed hotkey
  (`CommandOrControl+Shift+D`), read-only clipboard access. All constants,
  no settings surface (I1).
- `src/renderer/` — bridge-driven render tree (`OverlayCard`, `ShellApp`);
  renderer makes zero network calls (CSP `connect-src 'none'`).

### Run / test

```sh
cd overlay
npm install
npm test          # vitest (29 tests: snapshot matrix §9 rows 1–8+10,
                  # diff-flow over real HTTP via the generated client,
                  # ≤50 ms render assertion per fixture) + tsc typecheck
npm start         # build + launch the shell (needs a display or
                  #   --no-sandbox --ozone-platform=headless for a smoke run)
```

A full loop against the fixture mock: `npm run mock` in `web/`, then
`npm start` here, copy an item in game, press the hotkey.

### Deferred to the provisioned box (issue #34) — NOT claimed here

Native verification ACs of issue #11: real OS hotkey delivery, always-on-top
behavior over windowed-fullscreen, hide-on-game-focus-loss, and real
clipboard timing. The scaffold configures these but cannot verify them
headless; `overlay/bench/` holds the measurement harness.

Chip one-tap re-diff (spec §6.2/§7, snapshot rows 9/11) is TASK-204 (#12).
