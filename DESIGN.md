# How the coregistration and spatial transformation services are built, and the rules for changing them

## Overview

Two compute functions exposed as separate long-running processes, spoken to over
JSON on loopback:

| Service | Port | Endpoint | Does |
|---|---|---|---|
| coregistration | 8001 | `POST /v1/coregister` | two images → the transform between them |
| spatial transformation | 8002 | `POST /v1/spatial-transform` | image + transform + landmark → transformed image + landmark |

Orchestration is a client of both and owns neither. The algorithms are carried
over from the research code unchanged and produce bit-identical output.

## Code map

```
src/
  mri_contract/schema.py            types, validation, error codes, versions
  mri_core/transforms.py            transform primitives (verbatim - do not edit)
  mri_core/coregistration.py        coregister()
  mri_core/spatial.py               spatial_transform()
  mri_services/runtime.py           transport, bounds, logging, lifecycle
  mri_services/*_service.py         one module per endpoint

demo_orchestrator.py                throwaway demo, not device software
coregistration_exercise.py          original research code, kept for comparison
helper_functions.py                 "
generate_data.py                    "
```

Where things go:

| Changing | Edit |
|---|---|
| a request or response field | `mri_contract/schema.py` |
| a validation rule | `mri_contract/schema.py`, or `mri_services/runtime.py` if it needs a decoded image |
| the maths | `mri_core/` — read the invariants first |
| HTTP behaviour, logging, bounds | `mri_services/runtime.py` |
| a port, a route | the relevant `mri_services/*_service.py` |

## Data flow

```
orchestrator ──POST──▶ coregistration :8001
                          validate → decode images → coregister() → stamp case
                       ◀── Transform

orchestrator ──POST──▶ spatial transformation :8002
                          validate → decode image → bounds → case binding
                                   → spatial_transform()
                       ◀── image + landmark
```

Both endpoints read as a numbered list of steps in the service module. Each step
either raises a `ContractViolation` or produces a value the next step needs.
Nothing continues on failure.

`Transform` is the central type — frozen, and carrying the things the research
code left implicit:

| Field | Notes |
|---|---|
| `scale`, `rotation_deg`, `shift` | the parameters themselves |
| `order` | `"scale,rotate,shift"` — needed to invert correctly |
| `rotation_centre` | `"image_centre"` |
| `model` | `"similarity_2d"` — no skew term |
| `source_frame`, `target_frame` | pixel frames, not millimetres |
| `issued_for_case_id` | stamped by coregistration, checked by spatial transformation |

Landmarks and parameters travel as explicit fields, never in image metadata. PIL
drops `img.info` on save, so the research code's side channel disappears the
moment the functions run in separate processes.

## Invariants

Breaking any of these breaks an argument the submission depends on.
Invariants 1 and 9 are enforced by `tools/check_invariants.py`, which runs
in CI and locally with `uv run python tools/check_invariants.py`.

**1. `mri_services` → `mri_core` → `mri_contract`, never reversed.**
`mri_contract` is standard library only; `mri_core` adds Pillow. Neither may
import Flask. This is what lets transport be classified below the compute core —
a transport defect cannot alter a computed result. Checked in CI.

**2. Validate once, at the boundary.** The core assumes its inputs are already
valid and re-checks nothing. Scattered re-validation inside the maths leaves no
single place to point at when asked which checks run, and the two copies drift.

**3. Every check names the value it inspects and the source it derives from.**
Interface contract, data model, or a specific line of arithmetic — in a comment
next to the check. A check justified only by caution does not go in. See
`SCALE_ZERO` in `schema.py` for the shape: it exists because `spatial_transform`
computes `1/sx`.

**4. Don't edit the verbatim bodies in `mri_core`.** Function names keep their
leading underscores so "unchanged" is provable by diff. There is no verification
suite and no ground-truth oracle, so a behaviour change is currently
indistinguishable from a regression. Fixes go behind an equivalence fixture and a
test that fails before and passes after.

This includes the defects carried over from the research code. They are real and
they are deliberate -- each is recorded in the docstring of the module it lives
in, with the evidence. Read those before changing anything in `mri_core`.

**5. Fail closed.** Every path out of a handler is a complete valid result or a
defined `ErrorCode`. No bare `except`, no partial results, no default substituted
for a missing input. Exception details are logged, not returned — a message can
carry input-derived content and the response crosses a process boundary.

**6. No state between requests.** No caching, no module-level mutable data,
`threaded=False`. The device images one patient at a time. Statelessness is also
why there is no freshness check: the services hold no earlier image for a
timestamp comparison to discriminate against. Provenance binding via
`issued_for_case_id` is the derivable form of that instinct — it catches a
transform paired with the wrong case, and does not claim to detect tampering.

**7. Loopback is a constant, not configuration.** No auth, no TLS, same-machine
trust assumption, and a portable scanner that will sit on hospital networks. An
environment variable for the bind address means one typo exposes it. Ports are
configurable and validated.

**8. No clinical numbers in source.** Plausibility bounds on the transform and
the rejection threshold on registration quality both need values only the
clinical team can supply. An invented number reads as a verified requirement.
`quality_metric` ships as `null` so adding it later is not a breaking change.

**9. Every module declares `SAFETY_CLASS` and a rationale, matching the table
below.** `__init__.py` is exempt. Classes are provisional until a hazard analysis
exists — the rationale is the reviewable part, not the letter. CI checks the
constant against the table.

| Module | Class |
|---|---|
| `mri_core/*`, `mri_contract/schema.py` | C — output determines where the needle goes; validation is a risk control for that hazard |
| `mri_services/*` | B — cannot alter a result, only refuse. B rather than A because image decoding is on the clinical data path |
| `demo_orchestrator.py` | n/a — labelled in the file |

## Common changes

**Add a field to the contract.**
In `mri_contract/schema.py`: add it to the dataclass, to `_FIELDS`, to
`from_dict`, and to `as_payload`. Unknown fields are rejected, so a field absent
from `_FIELDS` will be refused rather than ignored. If it needs validating, add
the check in `from_dict` with its derivation comment. `mri_core` only changes if
the field affects the maths.

**Add a validation check.**
Decide where it lives by what it needs. Available from the JSON alone →
`schema.py`. Needs a decoded image → `runtime.py`, called from the endpoint
(this is why the landmark-bounds check is not in the contract: it indexes into a
specific image). Either way, add a member to `ErrorCode` — the orchestrator
branches on codes, not on messages — and write the derivation comment.

**Add an endpoint.**
New module in `mri_services/`, following either existing service: `create_app`,
`build_app`, `main`, a `SERVICE_NAME`, a port constant and its env var, and
`SAFETY_CLASS`. Register the console script in `pyproject.toml` under
`[project.scripts]`. Route under `/v1/`; a breaking change becomes `/v2` beside
it rather than a silent change in meaning.

**Replace the coregistration stub.**
Body of `coregister()` in `mri_core/coregistration.py` only. Both images are
already in the signature, unused, so the contract does not move. Then delete
`AcquisitionParams` and the `hfi_params` / `lfi_params` request fields — they
exist solely because the stub reads render parameters instead of pixels — and
bump `ALGORITHM_VERSION`.

**Change ports.**
`MRI_COREGISTRATION_PORT` / `MRI_SPATIAL_TRANSFORM_PORT`, or the `DEFAULT_PORT`
constant in the service module. Values are validated on the way in, not silently
defaulted.
