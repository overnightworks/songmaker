# Coverage & Logging Audit

You are auditing a codebase for test coverage gaps and missing logging at system boundaries. Read `CLAUDE.md` for conventions.

## Context

This project has ~940 backend tests and 90%+ coverage. The gaps aren't in volume — they're in **what** is tested. Tests verify behavior (retry, timeout, response shape) but often don't assert the **correctness of outgoing requests** to external systems. Similarly, logging captures results but not inputs — when something goes wrong at a boundary, you can't trace what was sent.

Recent example: the `seed` parameter was silently ignored by ACE-Step for months because (a) no test asserted the request payload contained `use_random_seed: false`, and (b) logs showed the returned seed but not the requested seed.

## Your Task

### Phase 1: Document external contracts

Before writing tests, you need to know what correct behavior looks like. Read the external system docs and document the **actual API contracts** at each boundary:

1. **ACE-Step API** — Read `docs/acestep.md` and `src/acestep_engine/client.py`. Then **web-search** for the current upstream API docs (start with `https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md`). Don't copy the API spec into our docs (it goes stale). Instead, verify our client sends what the upstream expects — especially fields with non-obvious defaults (like `use_random_seed`). If you find mismatches, fix the client code.

2. **Claude API** — Read `src/songmaker_cli/claude/`. The Anthropic SDK is the contract — check that our usage matches what the SDK actually does. Any fields we set that could be silently ignored?

3. **Redis patterns** — Read `src/songmaker_cli/redis_client.py` and `src/songmaker_cli/constants.py`. The key prefixes, Lua scripts, TTL semantics, and session cache contract are already in code — just verify the Lua scripts do what their callers assume.

### Phase 2: Payload assertion tests

For each external boundary in `src/acestep_engine/client.py`:

1. Read existing tests in `tests/test_client.py`
2. Add tests that **assert the payload content** sent to external APIs, not just the return value. Examples:
   - When `config.seed=42`, assert payload contains `{"seed": 42, "use_random_seed": false}`
   - When `config.seed=-1`, assert payload contains `{"use_random_seed": true}`
   - When `config.instrumental=True`, assert payload contains `{"instrumental": true}`
   - When `config.think_mode="off"`, assert payload contains `{"thinking": false}`
   - Assert all required fields are present in every payload

For `src/songmaker_cli/claude/`:
1. Read existing tests
2. Add tests that assert the messages/tools sent to Claude match what we intend

### Phase 3: Boundary logging

Add logging at system boundaries where **inputs** are not currently logged. The goal: when something goes wrong, you can reproduce the exact request that was sent.

Rules:
- Log at DEBUG level (not INFO — these are high-volume)
- Log the **input** to the external call, not just the output
- Don't log secrets, tokens, or full audio bytes
- Use structured logging (`log.debug("msg", key=value)` pattern)

Check these locations:
1. `src/acestep_engine/client.py` — `_submit_task()`: log the payload (or at least seed, steps, duration, model params)
2. `src/songmaker_cli/claude/provider.py` or equivalent — log the model, message count, tool names
3. `src/songmaker_cli/scoring/subprocess_runner.py` — log which scorers are requested, config
4. `src/songmaker_cli/jobs.py` — `_update_job()`: already logs on failure, but doesn't log the status transition on success

### Phase 4: Coverage check

Run the full test suite with coverage:

```bash
pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov-report=term-missing
```

For any module below 90% coverage (excluding `scoring/*`, `main.py`):
1. Read the uncovered lines
2. If they're reachable code paths (not just `if __name__ == "__main__"` guards), write tests
3. Focus on error paths and edge cases, not happy paths (those are already covered)

## What NOT to do

- Don't add logging inside hot loops (audio processing, scorer iterations)
- Don't add tests for trivial getters/setters
- Don't restructure existing tests — add new ones
- Don't change any behavior — this is observability only
- Don't log at INFO/WARNING for routine operations — DEBUG only for boundary tracing

## Checks

```bash
ruff check src/ tests/
pytest tests/ -n auto -q --cov=songmaker_cli --cov=audio_engine --cov=acestep_engine --cov-report=term-missing
```

All existing tests must still pass. Coverage should not decrease.
