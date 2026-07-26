# Differential corpus

Each directory in `builds/` contains one real Path of Building export and a
`metadata.json` record. Sources are pinned to an immutable upstream commit.
The imported build data is GPL-3.0; see `SOURCE_LICENSE`.

`metadata.json` deliberately separates a real build from its future
differential case. `oracle.status` remains `pending` until a human captures
desktop-PoB output. The headless wrapper must never generate its own oracle.

Validate structure while oracle capture is pending:

```sh
./engine/corpus/run_corpus.sh --allow-pending
```

The default command is the CI form. It rejects pending cases, invokes the
TASK-101 CLI for each captured case, canonicalizes JSON, and fails on any
mismatch:

```sh
POBCALC=./engine/pobcalc ./engine/corpus/run_corpus.sh
```

Before changing a case to `captured`, add `candidate_item.txt` and
`expected.json`, then set `candidate_item` and `oracle.file` in its metadata.

