# %%
import json
from helper_functions import (
    _translate, _rotate, _scale,
    _translate_pt, _rotate_pt, _scale_pt, coregister,
    get_prostate_location_from_user,
)

def spatial_transform(img, params):
    """Apply the inverse of `params` to `img` and to its landmark."""
    (sx, sy), rot, (tx, ty) = params["scale"], params["rotation"], params["shift"]
    cx, cy = img.width/2, img.height/2

    out = img
    out = _scale(out, 1/sx, 1/sy)       # undo the scale
    out = _rotate(out, rot)             # undo the rotation
    out = _translate(out, -tx, -ty)     # undo the shift

    p = get_prostate_location_from_user(img)
    if p:
        p = _scale_pt(p, 1/sx, 1/sy, cx, cy)
        p = _rotate_pt(p, rot, cx, cy)
        p = _translate_pt(p, -tx, -ty)
        out.info["landmark"] = json.dumps(p)
    out.info["params"] = img.info.get("params", "{}")
    return out

# %%
from pathlib import Path
from PIL import Image
from helper_functions import compare, mark_biopsy_site

output_dir = Path("output")
output_dir.mkdir(exist_ok=True)

for patient in range(1, 7):
    hfi = Image.open(f"./patient_{patient}.hfi.png")
    lfi = Image.open(f"./patient_{patient}.lfi.png")

    coregistration_params = coregister(hfi, lfi)
    sthfi = spatial_transform(hfi, coregistration_params)

    prostate_location = get_prostate_location_from_user(sthfi)

    comparison = compare(
        (hfi, f'hfi - patient {patient}'),
        (mark_biopsy_site(lfi, prostate_location), f'lfi - patient {patient}'),
        (mark_biopsy_site(sthfi, prostate_location), f'sthfi - patient {patient}'),
    )

    out_path = output_dir / f"patient_{patient}_comparison.png"
    comparison.save(out_path)
    print(f"Saved {out_path}")

    try:
        comparison.show()
    except Exception as e:
        print(f"Could not open image viewer ({e}); see {out_path} instead")
#%%