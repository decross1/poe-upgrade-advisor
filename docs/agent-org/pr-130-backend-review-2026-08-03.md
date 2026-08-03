# PR #130 backend review — REQUEST_CHANGES

Reviewed exact head `3b2efe74ab91f9b01017e3eb114de58e4d8cd166` for ledger
message `e7ca169a-2c19-413f-8860-cadfb995d327`.

## Verdict

Do not merge PR #130. Its exact head fails the repository test suite, it
touches protected packet paths without the required `protected-change` label,
and it is now superseded by merged PR #131. The TASK-214 renumber is already on
`main`; issue #125 subsequently records the backend and frontend stages as
complete. Closing PR #130 is preferable to updating a stale duplicate.

## Execution evidence

Commands run from a detached checkout of the exact PR head:

```text
python3 -m pytest tests packaging -q
python3 agents/packets/validate.py --all
python3 scripts/check_invariants.py
git diff --check HEAD^ HEAD
```

Result tail:

```text
Extra items in the left set:
'TASK-214-S1.json'
'TASK-214-S2.json'
Extra items in the right set:
'TASK-213-S2.json'
'TASK-213-S1.json'
FAILED tests/test_packets.py::test_every_example_packet_validates
1 failed, 581 passed in 30.67s
packet validation: 19 valid
doctrine invariants: OK
RESULT pytest=1 packet_validation=0 invariants=0 diff_check=0
```

`EVIDENCE-SHA256:2556f84e82de4b78ef3d9485a5f78fd23d4533424571365cc11b780279062bef`

The hash covers the complete 97-line execution log. The full log stayed outside
the repository because the protocol requires the review comment to carry the
tail and hash, not generated test artifacts.

## Review checks

- The failing assertion is at `tests/test_packets.py:144`: PR #130 renames the
  packet files but does not update the pinned filename set.
- The packet JSON files independently validate and doctrine invariants pass.
- No contract or product-code surface is changed.
- `tasks/packets/*` is protected by `agents/merge_robot/patterns.py`; neither PR
  #130 nor issue #125 carries `protected-change`.
- PR #130 is merge-conflicting with current `main`. PR #131 already landed the
  renumber, so repairing this head would duplicate completed bookkeeping.

