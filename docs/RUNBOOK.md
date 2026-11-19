# LETRO runbook

This is a local, offline Python package. There is no server, database or migration
to operate. The runbook covers the checks a judge or maintainer runs and the
failures that are most likely on a fresh machine.

## Start here

```console
python --version                 # 3.11 or newer
python -m letro.verify           # one command, exits 0 on success
python -m unittest discover -s tests -q
python -m letro.jury
python -m letro.fuzz --quick
```

Expected results:

- verifier prints `TOTAL 100.00` and `RESULT: PASS`;
- the unit suite passes (100 tests on the shipped tree);
- the jury harness prints `RESULT: PASS` with 20/20 oracle and permutation checks;
- the quick fuzz prints `RESULT: PASS` over 100 episodes.

The full sweep is `python -m letro.fuzz --seeds 100` (500 episodes). It takes a
few minutes on two cores and is the check to run before changing the generator.

## Workbench

```console
python -m letro.ui
```

The server binds `127.0.0.1:8000` and opens a browser. It is read-only and serves
only the labelled train/dev episodes. Stop it with `Ctrl+C`. If the port is busy:

```console
python -m letro.ui --port 8010
```

The workbench is a demo surface; it is not part of the environment contract and it
never serves `truth.json`.

## Container

```console
docker build -t letro:1.0.0 .
docker run --rm letro:1.0.0
docker run --rm -p 8000:8000 letro:1.0.0 python -m letro.ui --host 0.0.0.0
```

The image runs `python -m letro.verify` by default. It installs no packages and
runs as the unprivileged `letro` user. If the daemon is not running, start Docker
Desktop and retry; the build needs no network beyond the base image.

## Rebuild the shipped artefacts

```console
python scripts/build_episodes.py
python scripts/record_trajectories.py
python scripts/evaluate_policies.py
python scripts/demo.py
```

`build_episodes.py` is deterministic. It rewrites the 20 episode directories and
`episodes/index.json`, including the SHA-256 of every open-file set. Re-run the
verifier afterwards; it checks those digests.

## Common failures

| Symptom | Cause | Action |
| --- | --- | --- |
| `episodes/index.json is missing` | the tree was copied without generated episodes | run `python scripts/build_episodes.py` |
| `SyntaxError` on `match` or `\|` types | interpreter older than 3.11 | install Python 3.11 and rerun |
| `ModuleNotFoundError: letro` | command run outside the repository root | `cd` to the directory containing `letro/` |
| Docker build cannot connect | Docker Desktop is stopped | start it, then rebuild |
| `OSError: address already in use` | another workbench is on port 8000 | use `--port 8010` |
| fuzz reports a failure | generator or invariant drift | keep the seed printed in the failure; fix the generator, never the check |
| jury reports a permutation failure | an ID or ordering dependency | reproduce with the printed seed and inspect `letro.permute` |
| verifier reports a digest mismatch | open files were edited or line endings changed | rebuild the episodes; the digest normalizes CRLF to LF |

## Hidden-seed check

The open episodes are labels, not the grading set. To approximate a hidden run:

```console
python -m letro.jury
python -m letro.fuzz --seeds 100
```

The jury uses seeds 7001-7020 with clean, composite and mixed configurations; the
fuzz uses seeds 30000-30099 across five presets. Neither reads `truth.json` during
an agent run: truth is held by the evaluator and used only for scoring.

## Rollback

There is no persistent state and no migration. To roll back a change, use the
previous git commit and re-run the verifier. If generated episodes changed, rebuild
them from the previous commit before comparing digests.

## Ownership

Maintainer: LETRO contributors. The project is a competition artefact, not a
professional audit service. Report a failing check with the command, the seed and
the full output.

