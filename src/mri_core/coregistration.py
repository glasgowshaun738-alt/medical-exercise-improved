"""Coregistration: derive the transform between a high-field and a low-field image.

SAFETY_CLASS: C (provisional)
SAFETY_CLASS_RATIONALE:
    The transform produced here is what the spatial transformation is driven
    by, and therefore what determines whether the transformed anatomy matches
    the patient on the scanner. Provisional pending hazard analysis; see
    SAFETY_CLASSIFICATION.md.

PROVENANCE:
    The arithmetic is copied verbatim from `helper_functions.coregister`. Only
    the way values arrive and leave has changed: parameters are passed in
    explicitly instead of being read out of `img.info`, and the result is a
    declared `Transform` instead of a loose dict.

    That is an interface change, not an algorithm change, and the distinction
    matters -- see `spatial.py` for the same statement about the real function.

WHAT THIS FUNCTION IS NOT:
    It is a stub. The original docstring reads "Assume this is doing something
    very clever to identify transformation params", and it does not look at a
    single pixel. It reads the render parameters that `generate_data` stamped
    into both images and subtracts one set from the other.

    That means its inputs are an artefact of the synthetic data, not of the
    clinical workflow: a real registration algorithm receives two images and
    nothing else. Both images are still accepted here, unused, so that the
    interface is the one the real algorithm will need and swapping the body in
    does not change the contract.
"""

from __future__ import annotations

from mri_contract.schema import (
    FRAME_HFI_PIXELS,
    FRAME_LFI_PIXELS,
    ROTATION_CENTRE_IMAGE_CENTRE,
    TRANSFORM_MODEL_SIMILARITY_2D,
    TRANSFORM_ORDER_SCALE_ROTATE_SHIFT,
    AcquisitionParams,
    Transform,
)

SAFETY_CLASS = "C"
SAFETY_CLASS_PROVISIONAL = True


def coregister(
    hfi_image,
    lfi_image,
    hfi_params: AcquisitionParams,
    lfi_params: AcquisitionParams,
) -> Transform:
    """Return the transform mapping the HFI frame onto the LFI frame.

    `hfi_image` and `lfi_image` are accepted and deliberately unused: see the
    module docstring. They are present so that replacing the stub with a real
    algorithm is a change to this body alone.

    Inputs are assumed already validated. Validation happens once, at the
    service boundary, against `mri_contract.schema`; re-checking here would
    leave two places to point at when asked which checks run, and they would
    drift.
    """
    # Arithmetic verbatim from helper_functions.coregister. The division by the
    # reference scale is why AcquisitionParams rejects a zero scale component
    # at the boundary.
    return Transform(
        scale=(
            hfi_params.scale[0] / lfi_params.scale[0],
            hfi_params.scale[1] / lfi_params.scale[1],
        ),
        rotation_deg=hfi_params.rotation_deg - lfi_params.rotation_deg,
        shift=(
            hfi_params.shift[0] - lfi_params.shift[0],
            hfi_params.shift[1] - lfi_params.shift[1],
        ),
        # The original returned a bare dict, leaving these four facts implicit.
        # They are stated because inverting the transform is impossible without
        # the first two, and reviewing its direction is impossible without the
        # last two. Their values are read off `generate_data.render`, whose
        # inner `T` applies scale, then skew, then rotation, then shift, about
        # the image centre.
        order=TRANSFORM_ORDER_SCALE_ROTATE_SHIFT,
        rotation_centre=ROTATION_CENTRE_IMAGE_CENTRE,
        model=TRANSFORM_MODEL_SIMILARITY_2D,
        source_frame=FRAME_HFI_PIXELS,
        target_frame=FRAME_LFI_PIXELS,
    )
