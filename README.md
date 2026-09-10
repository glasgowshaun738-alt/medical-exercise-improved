# Medical Software Exercise

Coregistration and spatial transformation as two independent medicalized
services. See [DESIGN.md](./DESIGN.md) for how the codebase is put together.

The baseline code is DeepSpin's, supplied for a technical exercise and
reproduced from
<https://gist.github.com/shallowtwist-ben/c5bdca75d27dd5d53f0b5e0d8380ca88>. It
is committed unchanged as the first commit on `main`, so everything added
afterwards is visible as a diff.

## Running it

Three terminals. Nothing starts anything else — the services are independent
processes and the orchestrator is a client, so on a real appliance the first two
become service unit files with no code change.

```bash
uv sync
uv run coregistration-service        # terminal 1, port 8001
uv run spatial-transform-service     # terminal 2, port 8002
uv run python demo_orchestrator.py   # terminal 3, once both are up
```

Output lands in `output/`, one comparison image per patient, identical to what
the original in-process script produced.

Ports are overridable with `MRI_COREGISTRATION_PORT` and
`MRI_SPATIAL_TRANSFORM_PORT`. The bind address is loopback only and not
configurable — see the comment in
[src/mri_services/runtime.py](./src/mri_services/runtime.py).

```bash
curl http://127.0.0.1:8001/health    # process alive
curl http://127.0.0.1:8001/ready     # able to serve  (503 until started)
curl http://127.0.0.1:8001/version   # contract, software and algorithm versions
```

## Interface

Two endpoints, one per process, both `POST` with a JSON body. Request and
response shapes are defined in
[src/mri_contract/schema.py](./src/mri_contract/schema.py).

```
POST :8001/v1/coregister
  { case_id, hfi_png_b64, lfi_png_b64, hfi_params, lfi_params }
  → { case_id, transform, quality_metric, ...versions }

POST :8002/v1/spatial-transform
  { case_id, image_png_b64, transform, landmark? }
  → { case_id, image_png_b64, landmark, transform, ...versions }
```

Every refusal returns a defined error code and the exact field that caused it,
because orchestration is built by another team and has to branch on them:

```json
{ "error": "SCALE_ZERO",
  "field": "transform.scale[0]",
  "detail": "scale component is zero; the inverse transform divides by it",
  "contract_version": "v1" }
```

## Versions

Run with `python 3.14.3` and `uv 0.12.12`; the original was tested with
`python 3.12.5` / `python 3.10.14` and `uv 0.4.2`. Dependencies are pinned in
`uv.lock`, treated as the SOUP record rather than a build artifact.

---

# Background (from the supplied exercise)

This code is a simplification of the coregistration and spatial transformation code DeepSpin use.

DeepSpin's product is used to perform MRI guided biospy. The patient will come with a High Field MRI (HFI) which was used to diagnose that a biopsy is needed. During the proceedure we capture a Low Field MRI (LFI).

We use the LFI to 'coregister' the HFI. That means we use an algorithm to work out how to manipulate the older HFI image to match the position and current anatomy of the user based on the LFI we just took.

We use the parameters from coregistration to then spatially transform the HFI into a Spatially Transformed High Field Image (STHFI) which has the same image quality as the HFI but is updated to the current positioning of the patient.

`get_prostate_location_from_user` is a function which simulates a user clicking on a UI to identify where they want to biopsy. This is represented as a red circle in the spatially transformed output images.
