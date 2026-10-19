# dispatchkit

A small webhook delivery worker: retry with backoff, keep a delivery ledger,
and never send the same event twice.

## Tests

```bash
python -m pytest -q
```

## Conventions

- The tests are the spec. Do not edit them.
- Keep the public function names and signatures.
- A retry is 1-based: the first retry is attempt 1.
- An event is identified by `(kind, id)`. Two event types may share an id.
