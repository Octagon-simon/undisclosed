# Real-work fixture

The slugify demo proves the loop works. It does not prove the agent can read a
codebase. This fixture is the next step: three files, three interacting bugs,
thirteen tests, and a rule that the tests do not change.

## The task

`dispatchkit` is a webhook delivery worker. The bug report in
[dispatchkit/TASK.md](dispatchkit/TASK.md) names three symptoms:

1. An invoice and a receipt that share an event id collide in the delivery
   ledger, so one is dropped as a duplicate.
2. A 429 from the provider stops the retry loop after the first attempt.
3. The first retry waits twice as long as the README says it should.

The fixes are in three different files (`store.py`, `worker.py`, `backoff.py`).
The agent has to read the tests, find the contract, and change the code without
touching the tests.

## Baseline

```text
8 failed, 5 passed
```

The failures are intentional. Run it from `dispatchkit/`:

```bash
python -m pytest -q
```

## What a proof should publish

For a run to count, publish all of these:

- the task prompt and the starting commit;
- the baseline test output;
- the agent's diff;
- the final test output;
- the number of human interventions and the wall-clock time;
- the model and provider used.

A green test run alone is not the proof. The diff and the interventions are.

## Why this is harder than slugify

Slugify is one pure function with a spec in the prompt. This task has state
(the ledger), a retry loop, and an exception contract that only shows up when
two modules interact. A model that pattern-matches the prompt will fix the
backoff and miss the dedupe. That is the difference the fixture is meant to
expose.
