# TASK-213 — PM protected-path review: APPROVE

- **Task / issue:** TASK-213, [#123](https://github.com/decross1/poe-upgrade-advisor/issues/123)
- **Author:** backend
- **Reviewer:** pm (arbiter role not invoked; no dispute)
- **Commit under review:** `ead5b5af3b52e8aae3381102abadeef542cca8e1`
- **Branch:** `backend/TASK-213-engine-integration-jsonschema` (tip == commit, pushed)
- **Verdict:** **APPROVE**
- **Evidence:** `docs/reviews/TASK-213-evidence.log`
  `EVIDENCE-SHA256:c978b93fa8d793d9bf995b761f9dfe536c2ee030fa71a639ab8cf549ffe45156`

## Why this review exists

The diff touches `.github/workflows/ci.yml`, a protected path (AGENTS.md rule 5).
#123 carries `protected-change`, which authorizes the edit; AGENTS.md's definition
of done then requires counterpart review rather than the green-tier
report-and-stop path. The commit reached `main` during packet startup, so there is
no open PR — this record is the review artifact.

## What was verified, in the order of `docs/REVIEW_PROTOCOL.md` §"What reviewers verify"

1. **Tests pass, executed not read.** The pinned Lua runtime was built and the
   `PathOfBuilding` submodule initialized in the review worktree, then the job's
   own test step was run: `python3 -m unittest discover -s engine/tests -v` →
   `Ran 29 tests`, `OK`, **0 skips**, all three `GAME_CLIPBOARD_RESULT` markers
   emitted. Both bare-worktree failure modes were ruled out as reviewer-environment
   artifacts, not defects: an uninitialized submodule produced 23 errors, and an
   unbuilt runtime would have silently *skipped* the cases the acceptance criteria
   name — the same environment blindness that hid the original defect.

2. **Acceptance criteria (#123), all four met.**
   - `engine-integration` installs `jsonschema` alongside `pyyaml` — confirmed in
     the landed workflow.
   - Green with `test_server_adapter` collected and its game-clipboard cases
     *executed*: job log shows all five `RealServerAdapterTest` cases `... ok`,
     including `test_game_clipboard_items_reach_real_worker`, and zero skips.
   - Green on `main` after the merge: run **30842024806**, `event=push`,
     `headBranch=main`, `headSha=ead5b5a`, all 14 jobs `success`.
   - No change to the schema validation and no test skipped or deleted: the diff
     is one file, `.github/workflows/ci.yml`, six added lines of which five are a
     comment.

3. **Causal claim falsified in both directions**, rather than taken on trust.
   With `jsonschema` blocked by an import stub, discovery fails at collection with
   `ImportError: Failed to import test module: test_server_adapter` — reproducing
   the whole-job failure exactly as the commit message describes. With it present,
   collection succeeds. The diagnosis is correct, not merely plausible.

4. **No doctrine violation.** Workflow-only change; no product surface, no
   inference behavior, nothing touching I1/I2/I5 or S1–S3.

5. **No gate weakening (AGENTS.md rule 6).** This is the load-bearing check for
   this task, because three cheaper "fixes" were available and all three would
   have been adversarial: make the import lazy, skip the test, or drop the
   contract-schema assertion. The author took none of them. `jsonschema.validate`
   against `contracts/verdict.schema.json` remains at
   `engine/tests/test_server_adapter.py:129`. The fix adds a dependency; it
   removes no coverage.

6. **Blast radius.** One protected file, authorized. I independently re-ran the
   author's collateral audit rather than accepting it: of the three jobs with a
   thin install list, `assumptions-fixtures` and `windows-runtime-build` are
   clean. `windows-runtime-build` needed a real check, not an eyeball — it
   installs `pyyaml` only and does run Python (`python -m engine.runtime_parity`),
   so it is the same shape of risk; importing that module with `jsonschema`
   blocked succeeds, so it is green today. The author's conclusion holds.

## Findings that do not block

- `windows-runtime-build` passes only because `engine.runtime_parity`'s import
  closure happens not to reach `jsonschema` — a property no check enforces. That
  is the third instance of the class, and it belongs to the guard work in
  [#126](https://github.com/decross1/poe-upgrade-advisor/issues/126), not to this
  P0 unblock. Recorded there.

## Process note (for the retro, not against this change)

The defect was not the missing dependency; it was that `main`'s CI status went
unread across four merges while local suites were treated as proof. The author
says so plainly in the commit message. The durable fix is mechanical (#126) —
"remember to check CI" is not a control. No action against this commit.

## Reversal condition

Revisit if #126 lands a dependency-declaration mechanism that makes the inline
`pip install pyyaml jsonschema` list redundant; at that point this line should be
replaced by the generated one, not duplicated alongside it.
