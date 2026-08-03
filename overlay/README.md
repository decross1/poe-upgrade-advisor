# overlay/ — Verdict card overlay (Owner: Frontend)

Tauri preferred (small footprint helps I6); decide via ADR in TASK-201.
Flow: detect the game's own Ctrl+C item text on the clipboard →
POST /diff (server canonicalizes) → render VerdictCard (Tier 1) →
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
  headless-tested modules (`clipboardPipeline`, `diffFlow`, `diffRequest`).
- `src/clipboardWatcher.ts` — read-only, change-deduplicated clipboard sampler;
  recognizes only PoE's `Item Class:` + `Rarity:` header and ignores all other
  content without a request.
- `src/diffFlow.ts` — captured item → /diff → state machine (spec §8.4:
  HIDDEN/LOADING/VERDICT/ERROR_*; RULING-19 3000 ms timeout; RULING-20
  status-code-only errors; a newer capture supersedes an in-flight request).
- `src/serverEndpoint.ts` — backend swap is config-only: the client targets
  `servers[0].url` from `contracts/openapi.yaml` (`http://127.0.0.1:47791/api/v0`,
  the TASK-206 fixture mock today) unless `POE_ADVISOR_SERVER_URL` is set.
  `POE_ADVISOR_WEB_URL` likewise overrides the web-app deep-link base.
- `src/window.ts` / `src/clipboardText.ts` — Electron adapters: fixed 340 px
  frameless always-on-top window and read-only clipboard access. All
  constants, no settings surface (I1).
- `src/renderer/` — bridge-driven render tree (`OverlayCard`, `ShellApp`);
  renderer makes zero network calls (CSP `connect-src 'none'`).

### Run / test

```sh
cd overlay
npm install
npm test          # vitest (clipboard pipeline + snapshot matrix §9,
                  # diff-flow over real HTTP via the generated client,
                  # ≤50 ms render assertion per fixture) + tsc typecheck
npm start         # build + launch the shell (needs a display or
                  #   --no-sandbox --ozone-platform=headless for a smoke run)
```

A full loop against the fixture mock: `npm run mock` in `web/`, then
`npm start` here and copy an item in game.

### Deferred to the provisioned box (issue #34) — NOT claimed here

Always-on-top behavior over windowed-fullscreen, hide-on-game-focus-loss, and
real clipboard timing cannot be verified headless; `overlay/bench/` holds the
measurement harness. Global-hotkey work, if needed, is a later stage.

Chip one-tap re-diff (spec §6.2/§7, snapshot rows 9/11) is TASK-204 (#12).
