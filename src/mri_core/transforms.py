"""Primitive image and point transform operations.

SAFETY_CLASS: C (provisional)
SAFETY_CLASS_RATIONALE:
    These operations determine where the transformed anatomy and the biopsy
    landmark end up. Their output feeds the target the needle is driven to, so
    an error here is not recoverable downstream. Provisional pending hazard
    analysis; see DESIGN.md.

PROVENANCE:
    Every function body in this module is copied verbatim from
    `helper_functions.py` in the supplied R&D code. Names are kept identical,
    including the leading underscores, so that "unchanged" is verifiable by
    diff rather than by assertion. Nothing here is rewritten, reordered or
    optimised.

    That restraint is deliberate rather than lazy. There is no equivalence
    baseline for this software yet -- no reference outputs, no verification
    suite -- so any behaviour change made now could not be distinguished from
    a regression. The defects found while reading this code are recorded in
    DESIGN.md and left in place.

    The one documented defect that lives here is `_rotate`'s sign convention:
    it is only correct in combination with the specific call order used by
    `spatial_transform`, and neither the convention nor the coupling is stated
    anywhere in the original. That is recorded, not corrected.
"""

from math import cos, sin, radians

from PIL import Image

SAFETY_CLASS = "C"
SAFETY_CLASS_PROVISIONAL = True


def _translate(im, dx, dy):
    return im.transform(im.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy),
                        resample=Image.BILINEAR, fillcolor="white")

def _rotate(im, deg):
    return im.rotate(deg, resample=Image.BILINEAR, fillcolor="white")

def _scale(im, fx, fy):
    cx, cy = im.width/2, im.height/2
    return im.transform(im.size, Image.AFFINE,
                        (1/fx, 0, cx*(1 - 1/fx), 0, 1/fy, cy*(1 - 1/fy)),
                        resample=Image.BILINEAR, fillcolor="white")

def _translate_pt(p, dx, dy):
    return (p[0] + dx, p[1] + dy)

def _rotate_pt(p, deg, cx, cy):
    ca, sa = cos(radians(deg)), sin(radians(deg))
    x, y = p[0] - cx, p[1] - cy
    return (cx + x*ca + y*sa, cy - x*sa + y*ca)

def _scale_pt(p, fx, fy, cx, cy):
    return (cx + (p[0] - cx)*fx, cy + (p[1] - cy)*fy)
