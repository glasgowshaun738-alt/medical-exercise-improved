"""Spatial transformation: bring the high-field image into the current frame.

SAFETY_CLASS: C (provisional)
SAFETY_CLASS_RATIONALE:
    This is the function whose output the operator marks a biopsy site on. The
    transformed image and the transformed landmark are what the needle is aimed
    by, so an error here lands at the needle tip with nothing downstream to
    catch it. Provisional pending hazard analysis; see
    DESIGN.md.

PROVENANCE:
    The six transform calls below, their order, and their arguments are copied
    verbatim from `coregistration_exercise.spatial_transform`. What changed is
    only how data arrives and leaves:

      - the landmark is a parameter instead of being read from `img.info`;
      - the landmark is returned instead of being written to `out.info`;
      - `params` is a validated `Transform` instead of a loose dict.

    Interface change, not algorithm change. The arithmetic is untouched, and
    deliberately so: with no equivalence baseline and no verification suite,
    a behaviour change now would be indistinguishable from a regression.

    The reason the interface had to change is mechanical rather than stylistic.
    `img.info` is not persisted by PIL across `save()`, so once this function
    runs in a separate process from its caller -- which the orchestration team
    requires -- the landmark and parameters silently vanish rather than arriving
    wrong. The process split is what exposed the side channel.

DOCUMENTED DEFECT, NOT FIXED:
    The forward transform in `generate_data.render` applies scale, then skew,
    then rotation, then shift. This function undoes it by applying the inverse
    scale, then the inverse rotation, then the inverse shift -- the same order
    as the forward pass, rather than the reverse. Correct inversion requires
    reversing the order, because translation does not commute with scale or
    rotation.

    The supplied data agrees. The cases the generator's own comments mark
    "good" are the ones with no shift, where the remaining components are an
    isotropic scale and a rotation about the same centre, which do commute. The
    case it marks "bad" is the one that adds shift. Patients 2 and 3 carry no
    shift; patient 4 carries shift together with scale and rotation.

    It is left in place and recorded in DESIGN.md. Correcting it is a
    change to clinical behaviour and belongs behind a verification suite with a
    ground-truth oracle, not inside the merge request that introduces the
    service wrappers.
"""

from __future__ import annotations

from mri_contract.schema import Transform

from .transforms import (
    _rotate,
    _rotate_pt,
    _scale,
    _scale_pt,
    _translate,
    _translate_pt,
)

SAFETY_CLASS = "C"
SAFETY_CLASS_PROVISIONAL = True


def spatial_transform(
    img,
    transform: Transform,
    landmark: tuple[float, float] | None = None,
):
    """Apply the inverse of `transform` to `img` and to its landmark.

    Returns `(transformed_image, transformed_landmark)`. The landmark is
    `None` when none was supplied, which is the case before the operator has
    marked a biopsy site.

    Both the image and the landmark are driven by the same `Transform` object.
    In the supplied code they were driven by two separate unpacked copies of
    the same dict, so the two paths could be edited independently and disagree
    -- and a landmark that disagrees with the image it is drawn on is a
    misplaced target rather than a visible glitch.

    Inputs are assumed already validated at the service boundary: finite
    parameters, non-zero scale components, and a landmark inside the image
    bounds. Nothing is re-checked here.
    """
    (sx, sy) = transform.scale
    rot = transform.rotation_deg
    (tx, ty) = transform.shift
    cx, cy = img.width / 2, img.height / 2

    # Verbatim from coregistration_exercise.spatial_transform, including the
    # order. See the module docstring for why the order is wrong and why it is
    # nevertheless unchanged.
    out = img
    out = _scale(out, 1 / sx, 1 / sy)       # undo the scale
    out = _rotate(out, rot)                 # undo the rotation
    out = _translate(out, -tx, -ty)         # undo the shift

    out_landmark = None
    # The original wrote `if p:`. Since the supplied
    # `get_prostate_location_from_user` returns either a 2-tuple or None, and a
    # 2-tuple is always truthy, `is not None` is exactly equivalent here and
    # does not depend on the truthiness of a coordinate pair.
    if landmark is not None:
        p = landmark
        p = _scale_pt(p, 1 / sx, 1 / sy, cx, cy)
        p = _rotate_pt(p, rot, cx, cy)
        p = _translate_pt(p, -tx, -ty)
        out_landmark = p

    # `out.info` is deliberately not written. The caller receives the landmark
    # as a return value and the transform is echoed in the service response,
    # so nothing clinical depends on metadata that PIL will drop on save.
    return out, out_landmark
