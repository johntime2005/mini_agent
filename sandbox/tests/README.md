# sandbox tests

Pytest suite for the `mini-agent-sandbox` Python core. Originally contributed
by @wangzhangzhuo on 2026-05-01.

## Layout

```
tests/
├── conftest.py        # shared fixtures: SessionManager / sandbox_session pinned to tmp_path
├── unit/
│   ├── test_executor.py   # success / timeout / output-truncation paths
│   ├── test_policy.py     # CommandPolicy allow/deny rules
│   └── test_session.py    # SessionManager lifecycle
└── (future) integration/  # reserved for cross-process / real-network tests
```

All unit tests are hermetic — they run real subprocesses (because that's
exactly what the executor is supposed to do) but never touch the network or
anything outside `tmp_path`.

## Running

```bash
pip install -e ./sandbox     # install the package under test
pip install pytest
pytest sandbox/tests
```

## TODO

- [ ] Add `test_service.py` covering `SandboxService` end-to-end (file-write +
      execute round-trip) once we agree on the public API surface.
