"""Wire contract for the coregistration and spatial-transformation services.

SAFETY_CLASS: C (provisional)
SAFETY_CLASS_RATIONALE:
    This module implements the input validation that stands between the
    orchestrator and the compute core. That validation is a risk control for a
    hazard whose end effect is a needle placed in the wrong location, and a
    risk control cannot be classified below the hazard it mitigates. It is
    therefore provisionally C, the same class as the core.

    "Provisional" is load-bearing. A real classification is derived from a
    hazard analysis, and no hazard analysis exists for this software yet.
    Recording a class without one would be inventing a requirement, so the
    class is declared, the reasoning is recorded, and both are marked as
    pending review. See SAFETY_CLASSIFICATION.md.

Why this module exists at all:

    The supplied R&D code passes clinical payload through PIL image metadata.
    `coregister` reads `json.loads(img.info["params"])` from both images, and
    `spatial_transform` returns its landmark by writing `out.info["landmark"]`.
    PIL does not persist `.info` across `save()` unless PNG text chunks are
    written explicitly, so the moment these two functions run in separate
    processes -- which the orchestration team requires -- that channel silently
    disappears and the parameters arrive absent rather than wrong.

    Splitting the processes is what exposed this. Every field below that looks
    like bureaucracy is a value that used to travel in `img.info` and now has
    to be declared, because a side channel that silently drops data is not
    something a device can be built on.

This module depends only on the standard library. It must never import Flask,
`mri_services`, or `mri_core`: the orchestrator's demo client validates against
the same contract, and a contract that drags a web framework with it is not a
contract.
"""

from __future__ import annotations

import base64
import binascii
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping


# --------------------------------------------------------------------------
# Versions
#
# A regulated device must be able to state which software produced a given
# clinical result. Three separate versions are reported because they change
# for different reasons and at different rates: the wire contract, the build,
# and the algorithm behind it.
# --------------------------------------------------------------------------

CONTRACT_VERSION = "v1"

# Tracks pyproject `version`. Kept here rather than read from package metadata
# so that the value is identical whether the service runs installed or from a
# source checkout.
SOFTWARE_VERSION = "0.1.0"

# The algorithms are carried over from the R&D code unchanged. `0.0.0-rnd`
# records that fact: there is no released, verified algorithm version yet, and
# claiming one would misrepresent the state of the software.
ALGORITHM_VERSION = "0.0.0-rnd"


# --------------------------------------------------------------------------
# Frames of reference
#
# A transform is not "scale, rotation, shift" -- it is a mapping from one named
# frame to another. The supplied code never names either frame, so the
# direction of the transform is only recoverable by reading the call site.
# Naming them costs two strings and makes the direction reviewable.
#
# Both frames are pixel-index frames. They are NOT patient space in
# millimetres: PNG carries no pixel spacing, so no millimetre claim can be made
# from this data. Stated explicitly because an accuracy figure in pixels is not
# clinically meaningful, and that gap belongs in the writeup rather than being
# papered over by a units-free number.
# --------------------------------------------------------------------------

FRAME_HFI_PIXELS = "hfi_pixels"
FRAME_LFI_PIXELS = "lfi_pixels"
KNOWN_FRAMES = (FRAME_HFI_PIXELS, FRAME_LFI_PIXELS)


# --------------------------------------------------------------------------
# Transform parameterisation
#
# The supplied transform is a loose dict: {"scale", "rotation", "shift"}. Two
# things it needs in order to be applied or inverted correctly are absent from
# it, and live only in the author's head:
#
#   1. The order the components are applied in.
#   2. The centre that scale and rotation act about.
#
# Both are recoverable from `generate_data.render`, whose inner `T` is
# commented "about the centre, in this order" and applies
# scale -> skew -> rotate -> shift about the image centre. They are declared
# here as fields so that inverting the transform is a matter of reading the
# contract rather than reading the generator.
#
# This matters concretely. `coregistration_exercise.spatial_transform` undoes
# the transform by applying scale, rotate, shift in the SAME order as the
# forward pass rather than the reverse, which is only correct when the
# components happen to commute. The generator's own case labels agree: the
# cases it marks "good" carry no shift (isotropic scale does commute with
# rotation), and the case it marks "bad" is the one that adds shift. The defect
# is documented rather than fixed -- see MERGE_REQUEST.md for why no behaviour
# change lands before an equivalence baseline exists.
# --------------------------------------------------------------------------

TRANSFORM_ORDER_SCALE_ROTATE_SHIFT = "scale,rotate,shift"
KNOWN_TRANSFORM_ORDERS = (TRANSFORM_ORDER_SCALE_ROTATE_SHIFT,)

ROTATION_CENTRE_IMAGE_CENTRE = "image_centre"
KNOWN_ROTATION_CENTRES = (ROTATION_CENTRE_IMAGE_CENTRE,)

# `coregister` returns only scale, rotation and shift, while
# `generate_data.render` accepts a `skew` argument, so the model is narrower
# than the deformation the data source can produce. None of the six supplied
# patients use skew, but a commented-out case in the generator reads
# `render(rotation=20, skew=(0.5,0), ...) # accidentally ok` -- a plausible
# result obtained by accident, which is the failure signature that matters for
# a safety-critical path. Declaring the model means a future caller that needs
# deformation is refused rather than silently approximated.
TRANSFORM_MODEL_SIMILARITY_2D = "similarity_2d"
KNOWN_TRANSFORM_MODELS = (TRANSFORM_MODEL_SIMILARITY_2D,)


# --------------------------------------------------------------------------
# Bounds
#
# A device has fixed memory and serves one patient at a time. Unbounded
# anything is a hazard, so every bound is declared with the reason it exists.
# None of these are clinical thresholds; they are resource and contract limits,
# which is why they can be set here without clinical sign-off. Contrast with
# the plausibility bounds on the transform itself and the rejection threshold
# on registration quality, which are clinical decisions and are therefore
# absent rather than guessed.
# --------------------------------------------------------------------------

# Base64 inflates by 4/3. The supplied PNGs are 5-12 kB, so 8 MB is roughly
# three orders of magnitude of headroom while still refusing a payload that
# could exhaust memory.
MAX_REQUEST_BYTES = 8 * 1024 * 1024

# The supplied data is 300x300 after `render`'s final resize to OUT. The bound
# is generous rather than tight because the real acquisition size is not known
# here; its purpose is to refuse an image large enough to be a resource
# problem, not to assert what a valid scan looks like.
MIN_IMAGE_PIXELS = 16
MAX_IMAGE_PIXELS = 4096

# `helper_functions` builds every intermediate with `Image.new("RGB", ...)` and
# `fillcolor="white"`, and the supplied PNGs decode as RGB. Accepting a mode
# the transform helpers were never exercised against would be accepting
# untested behaviour.
ALLOWED_IMAGE_MODES = ("RGB",)


class ErrorCode(str, Enum):
    """Every rejection the services can emit.

    Enumerated rather than ad hoc because the orchestrator is written by
    another team and has to branch on these. A free-text error message is not
    an interface. Fail-closed means every path out of a handler is either a
    complete valid result or one of these codes -- never a default value
    substituted for missing input, and never a partial result.
    """

    SCHEMA_INVALID = "SCHEMA_INVALID"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    IMAGE_DECODE_FAILED = "IMAGE_DECODE_FAILED"
    IMAGE_MODE_UNSUPPORTED = "IMAGE_MODE_UNSUPPORTED"
    IMAGE_SIZE_OUT_OF_BOUNDS = "IMAGE_SIZE_OUT_OF_BOUNDS"
    TRANSFORM_INVALID = "TRANSFORM_INVALID"
    TRANSFORM_MODEL_UNSUPPORTED = "TRANSFORM_MODEL_UNSUPPORTED"
    SCALE_ZERO = "SCALE_ZERO"
    FRAME_UNKNOWN = "FRAME_UNKNOWN"
    LANDMARK_OUT_OF_BOUNDS = "LANDMARK_OUT_OF_BOUNDS"
    CASE_ID_MISMATCH = "CASE_ID_MISMATCH"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ContractViolation(Exception):
    """A request was refused at the boundary.

    Carries the code the orchestrator branches on and the field that caused it,
    so a rejection is actionable without reading the service log. `field` is a
    dotted path into the request body.
    """

    def __init__(self, code: ErrorCode, field: str, detail: str):
        super().__init__(f"{code.value} at {field}: {detail}")
        self.code = code
        self.field = field
        self.detail = detail

    def as_payload(self) -> dict[str, Any]:
        return {
            "error": self.code.value,
            "field": self.field,
            "detail": self.detail,
            "contract_version": CONTRACT_VERSION,
        }


# --------------------------------------------------------------------------
# Primitive validators
#
# Validation happens once, here, at the boundary. The core is not expected to
# re-check anything: scattered re-validation inside the maths reads as
# uncertainty about where the boundary is, and leaves no single place to point
# at when asked which checks run.
# --------------------------------------------------------------------------


def _require_mapping(body: Any) -> Mapping[str, Any]:
    if not isinstance(body, Mapping):
        raise ContractViolation(
            ErrorCode.SCHEMA_INVALID, "<body>", "request body must be a JSON object"
        )
    return body


def _reject_unknown_fields(body: Mapping[str, Any], allowed: tuple[str, ...]) -> None:
    """Refuse fields the contract does not define.

    Ignoring an unrecognised field means accepting a request whose sender
    believed it had an effect. On this path that is a silently wrong result
    rather than a refused one, so unknown fields are rejected.
    """
    for key in body:
        if key not in allowed:
            raise ContractViolation(
                ErrorCode.UNKNOWN_FIELD,
                key,
                f"field is not part of contract {CONTRACT_VERSION}",
            )


def _require_str(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(
            ErrorCode.SCHEMA_INVALID, key, "expected a non-empty string"
        )
    return value


def _require_finite(value: Any, field_path: str) -> float:
    """Numeric, real, and finite.

    NaN and infinity are rejected rather than allowed to propagate: both are
    valid floats that survive arithmetic silently and turn into nonsense pixel
    coordinates at the end of the pipeline. `bool` is excluded because it is a
    subclass of `int` and `True` as a scale factor is a type error, not a 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractViolation(
            ErrorCode.TRANSFORM_INVALID, field_path, "expected a number"
        )
    if not math.isfinite(value):
        raise ContractViolation(
            ErrorCode.TRANSFORM_INVALID, field_path, "expected a finite number"
        )
    return float(value)


def _require_pair(value: Any, field_path: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ContractViolation(
            ErrorCode.TRANSFORM_INVALID, field_path, "expected a pair [x, y]"
        )
    return (
        _require_finite(value[0], f"{field_path}[0]"),
        _require_finite(value[1], f"{field_path}[1]"),
    )


def _optional_str(value: Any, field_path: str) -> str | None:
    """A string, or absent. Empty and whitespace-only are rejected rather than
    normalised to None, because they indicate a caller that meant to send
    something."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(
            ErrorCode.SCHEMA_INVALID, field_path, "expected a non-empty string or null"
        )
    return value


def _require_enum(value: Any, allowed: tuple[str, ...], code: ErrorCode, field_path: str) -> str:
    if value not in allowed:
        raise ContractViolation(
            code, field_path, f"expected one of {list(allowed)}, got {value!r}"
        )
    return str(value)


def decode_png_b64(value: Any, field_path: str) -> bytes:
    """Base64 to PNG bytes, without touching PIL.

    Images travel as base64 inside the JSON body. That is a deliberate MVP
    choice and a bad production one: base64 inflates by a third and the whole
    payload is held in memory twice. The alternative -- multipart, or a shared
    store addressed by reference -- moves the problem to access control on that
    store, which is a larger decision than this patch. Recorded in
    MERGE_REQUEST.md rather than decided here.

    Decoding is split from image parsing so that a malformed transport
    encoding and a malformed image are different error codes. The orchestrator
    can retry one and must not retry the other.
    """
    if not isinstance(value, str) or not value:
        raise ContractViolation(
            ErrorCode.SCHEMA_INVALID, field_path, "expected base64-encoded PNG bytes"
        )
    try:
        # validate=True so that stray characters are an error rather than being
        # silently discarded, which would mean decoding a different image than
        # the caller sent.
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ContractViolation(
            ErrorCode.IMAGE_DECODE_FAILED, field_path, f"not valid base64: {exc}"
        ) from None


# --------------------------------------------------------------------------
# Transform
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Transform:
    """A 2D similarity transform with its order, centre and frames declared.

    Held frozen because a transform that is mutated after validation has not
    been validated. The same object is used for the image and for the landmark,
    which is the structural fix for the two diverging code paths in the
    supplied `spatial_transform`.
    """

    scale: tuple[float, float]
    rotation_deg: float
    shift: tuple[float, float]
    order: str = TRANSFORM_ORDER_SCALE_ROTATE_SHIFT
    rotation_centre: str = ROTATION_CENTRE_IMAGE_CENTRE
    model: str = TRANSFORM_MODEL_SIMILARITY_2D
    source_frame: str = FRAME_HFI_PIXELS
    target_frame: str = FRAME_LFI_PIXELS

    # Set by the coregistration service to the case the transform was computed
    # for, and required by the spatial transformation service to equal the
    # case on the request it arrives with.
    #
    # This is the whole reason the field exists. Splitting one function into
    # two processes is what creates the possibility of handing spatial
    # transformation a transform computed for a different patient, and a
    # stateless service holds nothing it could compare a bare case identifier
    # against. Carrying the case inside the transform gives it something.
    #
    # What it detects: an orchestrator that pairs the wrong transform with an
    # image. What it does not detect: a transform that was altered in transit.
    # Detecting that needs a signed binding and a key, which is a decision
    # about the trust boundary between these processes that has not been made.
    # Stated rather than quietly implied, because a check that appears to
    # authenticate and does not is worse than no check.
    issued_for_case_id: str | None = None

    _FIELDS = (
        "scale",
        "rotation_deg",
        "shift",
        "order",
        "rotation_centre",
        "model",
        "source_frame",
        "target_frame",
        "issued_for_case_id",
    )

    @classmethod
    def from_dict(cls, body: Any, field_path: str = "transform") -> "Transform":
        body = _require_mapping(body)
        _reject_unknown_fields(body, cls._FIELDS)

        for required in ("scale", "rotation_deg", "shift"):
            if required not in body:
                raise ContractViolation(
                    ErrorCode.TRANSFORM_INVALID,
                    f"{field_path}.{required}",
                    "required field is absent",
                )

        scale = _require_pair(body["scale"], f"{field_path}.scale")

        # `coregistration_exercise.spatial_transform` computes 1/sx and 1/sy to
        # invert the scale. A zero component is a division by zero, so this is
        # a defined failure of the input rather than an unlikely edge case. The
        # check is derived from that line of arithmetic, not from caution.
        for index, component in enumerate(scale):
            if component == 0.0:
                raise ContractViolation(
                    ErrorCode.SCALE_ZERO,
                    f"{field_path}.scale[{index}]",
                    "scale component is zero; the inverse transform divides by it",
                )

        return cls(
            scale=scale,
            rotation_deg=_require_finite(
                body["rotation_deg"], f"{field_path}.rotation_deg"
            ),
            shift=_require_pair(body["shift"], f"{field_path}.shift"),
            order=_require_enum(
                body.get("order", TRANSFORM_ORDER_SCALE_ROTATE_SHIFT),
                KNOWN_TRANSFORM_ORDERS,
                ErrorCode.TRANSFORM_INVALID,
                f"{field_path}.order",
            ),
            rotation_centre=_require_enum(
                body.get("rotation_centre", ROTATION_CENTRE_IMAGE_CENTRE),
                KNOWN_ROTATION_CENTRES,
                ErrorCode.TRANSFORM_INVALID,
                f"{field_path}.rotation_centre",
            ),
            model=_require_enum(
                body.get("model", TRANSFORM_MODEL_SIMILARITY_2D),
                KNOWN_TRANSFORM_MODELS,
                ErrorCode.TRANSFORM_MODEL_UNSUPPORTED,
                f"{field_path}.model",
            ),
            source_frame=_require_enum(
                body.get("source_frame", FRAME_HFI_PIXELS),
                KNOWN_FRAMES,
                ErrorCode.FRAME_UNKNOWN,
                f"{field_path}.source_frame",
            ),
            target_frame=_require_enum(
                body.get("target_frame", FRAME_LFI_PIXELS),
                KNOWN_FRAMES,
                ErrorCode.FRAME_UNKNOWN,
                f"{field_path}.target_frame",
            ),
            issued_for_case_id=_optional_str(
                body.get("issued_for_case_id"), f"{field_path}.issued_for_case_id"
            ),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "scale": list(self.scale),
            "rotation_deg": self.rotation_deg,
            "shift": list(self.shift),
            "order": self.order,
            "rotation_centre": self.rotation_centre,
            "model": self.model,
            "source_frame": self.source_frame,
            "target_frame": self.target_frame,
            "issued_for_case_id": self.issued_for_case_id,
        }

    def issued_for(self, case_id: str) -> "Transform":
        """Return a copy stamped with the case it was computed for."""
        return replace(self, issued_for_case_id=case_id)


# --------------------------------------------------------------------------
# Acquisition parameters
#
# `coregister` does not look at pixels. It reads the render parameters that
# `generate_data` stamped into `img.info["params"]` and subtracts one set from
# the other, which only works because the same generator produced both images.
# A real registration algorithm has no such side channel.
#
# These fields therefore exist to carry a property of the stub, not a property
# of the clinical workflow, and they are expected to disappear when the real
# algorithm lands. Saying so here is the point: an unexplained pair of
# parameter blocks in a device interface is exactly the kind of thing that
# survives into production because nobody remembered what it was for.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AcquisitionParams:
    """Render parameters of one supplied image. Stub-only; see note above."""

    scale: tuple[float, float]
    rotation_deg: float
    shift: tuple[float, float]

    _FIELDS = ("scale", "rotation_deg", "shift")

    @classmethod
    def from_dict(cls, body: Any, field_path: str) -> "AcquisitionParams":
        body = _require_mapping(body)
        _reject_unknown_fields(body, cls._FIELDS)
        for required in cls._FIELDS:
            if required not in body:
                raise ContractViolation(
                    ErrorCode.SCHEMA_INVALID,
                    f"{field_path}.{required}",
                    "required field is absent",
                )
        scale = _require_pair(body["scale"], f"{field_path}.scale")

        # `coregister` computes a[scale]/b[scale]. A zero in the reference
        # image's scale is a division by zero in that line.
        for index, component in enumerate(scale):
            if component == 0.0:
                raise ContractViolation(
                    ErrorCode.SCALE_ZERO,
                    f"{field_path}.scale[{index}]",
                    "scale component is zero; coregistration divides by it",
                )
        return cls(
            scale=scale,
            rotation_deg=_require_finite(
                body["rotation_deg"], f"{field_path}.rotation_deg"
            ),
            shift=_require_pair(body["shift"], f"{field_path}.shift"),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "scale": list(self.scale),
            "rotation_deg": self.rotation_deg,
            "shift": list(self.shift),
        }


# --------------------------------------------------------------------------
# Requests and responses
#
# `case_id` is on every message. The orchestrator generates it, and both
# services require it to be identical across the pair of calls for one case.
#
# This is provenance binding, and it is the derivable form of the instinct to
# check that an image is not stale. There is no freshness check in this
# contract: the services are stateless, hold no previous image, and have no
# reference clock they own, so at this boundary there is no second candidate
# image for a timestamp comparison to discriminate against. What the split into
# two processes does create is the possibility of handing spatial
# transformation a transform computed for a different case, and that is what
# `case_id` refuses. See MERGE_REQUEST.md.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CoregisterRequest:
    case_id: str
    hfi_png: bytes = field(repr=False)
    lfi_png: bytes = field(repr=False)
    hfi_params: AcquisitionParams
    lfi_params: AcquisitionParams

    _FIELDS = ("case_id", "hfi_png_b64", "lfi_png_b64", "hfi_params", "lfi_params")

    @classmethod
    def from_dict(cls, body: Any) -> "CoregisterRequest":
        body = _require_mapping(body)
        _reject_unknown_fields(body, cls._FIELDS)
        return cls(
            case_id=_require_str(body, "case_id"),
            hfi_png=decode_png_b64(body.get("hfi_png_b64"), "hfi_png_b64"),
            lfi_png=decode_png_b64(body.get("lfi_png_b64"), "lfi_png_b64"),
            hfi_params=AcquisitionParams.from_dict(
                body.get("hfi_params"), "hfi_params"
            ),
            lfi_params=AcquisitionParams.from_dict(
                body.get("lfi_params"), "lfi_params"
            ),
        )


@dataclass(frozen=True)
class SpatialTransformRequest:
    case_id: str
    image_png: bytes = field(repr=False)
    transform: Transform
    landmark: tuple[float, float] | None

    _FIELDS = ("case_id", "image_png_b64", "transform", "landmark")

    @classmethod
    def from_dict(cls, body: Any) -> "SpatialTransformRequest":
        body = _require_mapping(body)
        _reject_unknown_fields(body, cls._FIELDS)

        landmark = body.get("landmark")
        # Absent and null both mean "the operator has not marked a site yet",
        # which the supplied `get_prostate_location_from_user` already models by
        # returning None. Bounds are checked in the service, where the decoded
        # image dimensions are known -- a landmark is a pixel index into a
        # specific image, so it cannot be validated without that image.
        if landmark is not None:
            landmark = _require_pair(landmark, "landmark")

        return cls(
            case_id=_require_str(body, "case_id"),
            image_png=decode_png_b64(body.get("image_png_b64"), "image_png_b64"),
            transform=Transform.from_dict(body.get("transform")),
            landmark=landmark,
        )


def coregister_response(case_id: str, transform: Transform) -> dict[str, Any]:
    """Response body for a successful coregistration.

    `quality_metric` ships as null from the first version. The stub cannot
    compute a residual, and the threshold it would be compared against is a
    clinical decision that has not been made -- so inventing either would be
    inventing a requirement. The field exists anyway because a registration
    that fails while returning a plausible-looking transform is the dominant
    hazard on this path, and the service must eventually be able to refuse.
    Adding the field now means doing so is not a breaking change for the
    orchestrator.
    """
    return {
        "case_id": case_id,
        "transform": transform.as_payload(),
        "quality_metric": None,
        "contract_version": CONTRACT_VERSION,
        "software_version": SOFTWARE_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
    }


def spatial_transform_response(
    case_id: str,
    image_png_b64: str,
    landmark: tuple[float, float] | None,
    transform: Transform,
) -> dict[str, Any]:
    """Response body for a successful spatial transformation.

    The landmark is returned as an explicit field rather than attached to the
    returned image. The supplied code writes it to `out.info["landmark"]`,
    which does not survive the PNG round trip across a process boundary.

    The transform is echoed back so that the transformed image and the
    transform that produced it travel together. Without it the orchestrator
    holds an image whose provenance is only recoverable by correlating log
    lines.
    """
    return {
        "case_id": case_id,
        "image_png_b64": image_png_b64,
        "landmark": list(landmark) if landmark is not None else None,
        "transform": transform.as_payload(),
        "contract_version": CONTRACT_VERSION,
        "software_version": SOFTWARE_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
    }
