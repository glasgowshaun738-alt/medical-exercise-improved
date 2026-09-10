"""Spatial transformation service: its own process, its own port.

SAFETY_CLASS: B (provisional)
SAFETY_CLASS_RATIONALE:
    This module sequences validation and delegates the computation. It holds no
    geometry of its own, so a defect here is a refused or failed request rather
    than a wrong image. The computation it calls is class C, in
    `mri_core.spatial` -- its output is what the operator marks a biopsy site
    on. Provisional pending hazard analysis; see SAFETY_CLASSIFICATION.md.

PROCESS SEPARATION:
    Independent long-running service on its own port, started by the platform's
    service manager or by hand, never as a child of the orchestration code. Runs
    in a separate process from coregistration as well as from the orchestrator,
    which is the requirement in full.

STATE:
    None, for the same reasons as the coregistration service. In particular this
    service does not retain the transform from an earlier call: it receives the
    transform on every request and refuses one that was issued for a different
    case.
"""

from __future__ import annotations

from flask import Flask

from mri_contract.schema import SpatialTransformRequest, spatial_transform_response
from mri_core.spatial import spatial_transform

from .runtime import (
    configure_logging,
    create_app,
    decode_image,
    encode_image,
    json_response,
    log_event,
    port_from_env,
    read_json_body,
    require_case_binding,
    require_landmark_in_bounds,
    serve,
)

SAFETY_CLASS = "B"
SAFETY_CLASS_PROVISIONAL = True

SERVICE_NAME = "spatial-transform"
PORT_ENV_VAR = "MRI_SPATIAL_TRANSFORM_PORT"
DEFAULT_PORT = 8002

logger = configure_logging(SERVICE_NAME)


def build_app() -> Flask:
    app = create_app(SERVICE_NAME, logger)

    @app.post("/v1/spatial-transform")
    def spatial_transform_endpoint():
        # 1. Schema: required fields present and typed, unknown fields refused,
        #    base64 decodable, transform parameters finite, scale components
        #    non-zero, order and rotation centre recognised, transform model
        #    supported, frames named.
        req = SpatialTransformRequest.from_dict(read_json_body())

        # 2. Image: decodable, PNG, RGB, dimensions within resource bounds.
        img = decode_image(req.image_png, "image_png_b64")

        # 3. Landmark within the image it indexes into. Checked here because it
        #    needs the decoded dimensions. A marked site outside the acquired
        #    data is not a coordinate this service can transform meaningfully.
        require_landmark_in_bounds(req.landmark, img, "landmark")

        # 4. Provenance: this transform must have been issued for this case.
        #    Splitting coregistration and spatial transformation into separate
        #    processes is precisely what makes pairing a transform with the
        #    wrong image possible, so the check is derived from the interface
        #    rather than added out of caution.
        require_case_binding(
            req.case_id, req.transform.issued_for_case_id, "transform.issued_for_case_id"
        )

        # 5. Compute. One Transform object drives both the image and the
        #    landmark, so the two cannot diverge.
        out_img, out_landmark = spatial_transform(img, req.transform, req.landmark)

        log_event(
            logger,
            "spatial_transform_completed",
            service=SERVICE_NAME,
            case_id=req.case_id,
            image_size=f"{img.width}x{img.height}",
            transform=req.transform.as_payload(),
            landmark_supplied=req.landmark is not None,
            outcome="accepted",
        )

        return json_response(
            spatial_transform_response(
                case_id=req.case_id,
                image_png_b64=encode_image(out_img),
                landmark=out_landmark,
                transform=req.transform,
            ),
            200,
        )

    return app


def main() -> None:
    app = build_app()
    serve(app, logger, SERVICE_NAME, port_from_env(PORT_ENV_VAR, DEFAULT_PORT))


if __name__ == "__main__":
    main()
