# Tests

```bash
./tests/run.sh          # everything — provisions its own stack, prints one total
./tests/run.sh api      # the Python suites (no browser, no server, no network)
./tests/run.sh ui       # the browser suites
```

`run.sh` starts its own backend and dev server on ports of their own (`:8111`,
`:5111`), so it never touches a stack you already have running, and stops them
when it finishes.

| Suite | Checks | Covers |
|---|---:|---|
| `api/test_crowd.py` | 62 | Graph connectivity, Fruin LOS bands, capacity queueing, the choke point, mitigations, the 16-plan optimizer |
| `api/test_corridor.py` | 74 | Propagation, optimizer properties, precedence, hold window as policy, timeline coherence |
| `api/test_platform.py` | 94 | The policy register end to end over the API |
| `api/test_policy_units.py` | 114 | Schema, validation, line and semantic diff, reverse patch, the context seam, location, accounts |
| `api/test_protection.py` | 55 | Coverage arithmetic, risk exposure, the public headline, the caveat |
| `api/test_revert.py` | 51 | Revert vs restore, conflicts, no-ops, reverts that would produce an invalid document |
| `api/test_defect.py` | 82 | Both networks over HTTP: warm-up, uploads, guards, timings |
| `ui/three.mjs` | 46 | Both 3D scenes, every camera, playback, focus, no console errors |
| `ui/policy.mjs` | 61 | The register in the browser, end to end |
| `ui/signin.mjs` | 38 | The gate, the session, attribution across two people |
| `ui/defects.mjs` | 31 | The inspection tab |
| `ui/add-policy.mjs` | 20 | Adding a written standard |
| `ui/location.mjs` | 14 | Permissioned capture, and refusal |
| `ui/revert.mjs` | 13 | Undo from the change log |
| | **755** | |

## Two ideas run through all of it

**Each suite owns its state.** Every API suite provisions its own policy and
account store under `tests/.work/<suite>/` via `harness.bootstrap()`, and the
runner gives each browser suite a backend with an empty register. Share one store
and the third suite ends up asserting against whatever the first two left behind
— and the failure looks like a product bug rather than test bleed. Two things had
to be got right for that to hold: the runner `exec`s its servers so `$!` is the
process it can actually stop, and it waits for the port to be released before
deleting the store, or the old server keeps serving from a directory that no
longer exists.

**Assert the property, not the number.** A test that pins `peak_density == 17.39`
breaks the moment anyone tunes a constant, and tells you nothing about whether the
model is right. So instead:

- density rises when demand exceeds capacity, and the walk graph is one connected
  component (a flow model on a disconnected graph silently strands people);
- the crush lands on the articulation point every passenger must cross;
- metering removes it *without* stranding anyone;
- the optimizer never makes total delay worse than doing nothing;
- every train it reports as held is one it actually held, and every train held in
  a timeline is reported as a move;
- a train is only stood aside for one that outranks it under the precedence
  policy **in force**;
- narrowing the overtake window *in policy* makes the dispatcher stop taking
  those overtakes, and restoring it brings the original plan back;
- the traffic-weighted coverage figure moves toward a corridor when that
  corridor's traffic is doubled;
- the published headline's risk share is that shortlist's actual share of total
  exposure, and the shortlist is the head of the ranking rather than a hand-picked
  set.

Those hold whatever the timetable or the fixture is — and fail when the model
stops being a model.

## Notes

- The API suites need `backend/.venv` (or any `python3` with the requirements).
- `test_defect.py` and `ui/defects.mjs` need the ML extras and the checkpoints in
  `railsetu-m3/artifacts/`; without them they report the runtime as unavailable
  rather than failing.
- The browser suites use `playwright-core` from `frontend/node_modules` and find
  a headless Chromium in the Playwright cache. Override with
  `PLAYWRIGHT_CHROMIUM=/path/to/binary`.
- `RAILSETU_BASE` points a browser suite at an already-running stack, if you would
  rather drive your own.
