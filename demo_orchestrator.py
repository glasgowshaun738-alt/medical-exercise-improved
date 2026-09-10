"""DEMO HARNESS -- NOT DEVICE SOFTWARE.

SAFETY_CLASS: not applicable (not part of the device)

This script exists only to show that the two services work end to end. It
stands in for the orchestration code being built by another team, and it is
deliberately unpolished: no retries, no timeouts worth the name, no error
recovery, no tests. Nothing here should be read as a proposal for how the real
orchestrator should be written, and nothing here is verified.

What it does show, and what is worth looking at:

  - the orchestrator is a *client*. It does not start, stop, own or supervise
    either service, and it has no parent-child relationship with them. Start the
    services however you like -- see README.md -- and this script talks to
    whatever is listening.
  - it calls coregistration, takes the transform, calls spatial transformation
    with it, and takes the result. That is the whole interaction.
  - the case identifier is generated here, by the caller, and threaded through
    both calls. The services require the transform to have been issued for the
    case it is applied to.

It reads the render parameters out of `img.info`, which is exactly the side
channel the services were built to remove. That is intentional: in the real
system these values arrive from the acquisition pipeline and the UI. Here the
synthetic PNGs are the only source, so the demo carries the workaround and the
services do not.

Run it with both services already running:

    python demo_orchestrator.py
"""

import base64
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

# From the supplied R&D code. Used only for rendering the side-by-side output.
from helper_functions import compare, mark_biopsy_site, get_prostate_location_from_user

COREGISTRATION_URL = "http://127.0.0.1:8001"
SPATIAL_TRANSFORM_URL = "http://127.0.0.1:8002"

OUTPUT_DIR = Path("output")
PATIENTS = range(1, 7)


def post(url, payload):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # The services return a defined error code and the exact field. Printing
        # it is the whole of this harness's error handling.
        print(f"  rejected by {url}: {error.read().decode()}")
        raise SystemExit(1)


def require_ready(name, base_url):
    try:
        with urllib.request.urlopen(f"{base_url}/ready", timeout=5) as response:
            json.load(response)
    except (urllib.error.URLError, OSError) as error:
        print(f"{name} is not ready at {base_url}: {error}")
        print("Start both services first -- see README.md.")
        raise SystemExit(1)


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def acquisition_params(img):
    """Pull render parameters out of img.info. See the module docstring."""
    params = json.loads(img.info["params"])
    return {
        "scale": params["scale"],
        "rotation_deg": params["rotation"],
        "shift": params["shift"],
    }


def main():
    require_ready("coregistration", COREGISTRATION_URL)
    require_ready("spatial-transform", SPATIAL_TRANSFORM_URL)
    OUTPUT_DIR.mkdir(exist_ok=True)

    for patient in PATIENTS:
        case_id = f"demo-case-{patient}"
        hfi_path = f"./patient_{patient}.hfi.png"
        lfi_path = f"./patient_{patient}.lfi.png"
        hfi = Image.open(hfi_path)
        lfi = Image.open(lfi_path)

        coregistration = post(
            f"{COREGISTRATION_URL}/v1/coregister",
            {
                "case_id": case_id,
                "hfi_png_b64": b64(hfi_path),
                "lfi_png_b64": b64(lfi_path),
                "hfi_params": acquisition_params(hfi),
                "lfi_params": acquisition_params(lfi),
            },
        )

        result = post(
            f"{SPATIAL_TRANSFORM_URL}/v1/spatial-transform",
            {
                "case_id": case_id,
                "image_png_b64": b64(hfi_path),
                "transform": coregistration["transform"],
                # Stands in for the operator clicking a biopsy site in the UI.
                "landmark": list(get_prostate_location_from_user(hfi) or ()) or None,
            },
        )

        sthfi = Image.open(io.BytesIO(base64.b64decode(result["image_png_b64"])))
        landmark = tuple(result["landmark"]) if result["landmark"] else None

        comparison = compare(
            (hfi, f"hfi - patient {patient}"),
            (mark_biopsy_site(lfi, landmark), f"lfi - patient {patient}"),
            (mark_biopsy_site(sthfi, landmark), f"sthfi - patient {patient}"),
        )
        out_path = OUTPUT_DIR / f"patient_{patient}_comparison.png"
        comparison.save(out_path)
        print(f"{case_id}: saved {out_path}")

    print(f"\nDone. {len(PATIENTS)} cases through both services.")


if __name__ == "__main__":
    sys.exit(main())
