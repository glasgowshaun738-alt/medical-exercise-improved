"""Coregistration service: its own process, its own port.

SAFETY_CLASS: B (provisional)
SAFETY_CLASS_RATIONALE:
    This module sequences validation and delegates the computation. It holds no
    geometry of its own, so a defect here is a refused or failed request rather
    than a wrong transform. The computation it calls is class C, in
    `mri_core.coregistration`. Provisional pending hazard analysis; see
    SAFETY_CLASSIFICATION.md.

PROCESS SEPARATION:
    Runs as an independent long-running service, started by the platform's
    service manager or by hand, and never as a child of the orchestration code.
    The orchestrator is a client over loopback. That satisfies the separation
    requirement without Docker and without a parent-child relationship -- see
    MERGE_REQUEST.md for why those two were ruled out.

STATE:
    None. Nothing is retained between requests: no cached image, no previous
    case, no mutable module-level data. That is a deliberate property rather
    than an omission. Shared state between requests is where cross-patient
    contamination lives, and statelessness is also the reason this service has
    no freshness check -- it holds no earlier image that a newer one could be
    compared against. See `mri_contract.schema` for the derivation.
"""

from __future__ import annotations

from flask import Flask

from mri_contract.schema import CoregisterRequest, coregister_response
from mri_core.coregistration import coregister

from .runtime import (
    configure_logging,
    create_app,
    decode_image,
    json_response,
    log_event,
    port_from_env,
    read_json_body,
    serve,
)

SAFETY_CLASS = "B"
SAFETY_CLASS_PROVISIONAL = True

SERVICE_NAME = "coregistration"
PORT_ENV_VAR = "MRI_COREGISTRATION_PORT"
DEFAULT_PORT = 8001

logger = configure_logging(SERVICE_NAME)


def build_app() -> Flask:
    app = create_app(SERVICE_NAME, logger)

    # Versioned path. A breaking change to the contract arrives as /v2 beside
    # this one rather than as a silent change in meaning, because the
    # orchestrator is released on a different schedule by a different team.
    @app.post("/v1/coregister")
    def coregister_endpoint():
        # The sequence below is the whole request path, in order, and it is
        # meant to be read as a list. Every step either raises a
        # ContractViolation with a defined error code, or produces a value the
        # next step needs. There is no branch that continues on failure, and no
        # default substituted for a missing input.

        # 1. Schema: required fields present, types correct, unknown fields
        #    refused, base64 decodable, scale components non-zero.
        req = CoregisterRequest.from_dict(read_json_body())

        # 2. Images: decodable, PNG, RGB, dimensions within resource bounds.
        #    Needs Pillow, so it cannot live in the contract package.
        hfi = decode_image(req.hfi_png, "hfi_png_b64")
        lfi = decode_image(req.lfi_png, "lfi_png_b64")

        # 3. Compute. Inputs are validated; the core re-checks nothing.
        transform = coregister(hfi, lfi, req.hfi_params, req.lfi_params)

        # 4. Stamp the case the transform was issued for, so the spatial
        #    transformation service can refuse a transform paired with the
        #    wrong image. This is the binding that replaces the freshness check
        #    that cannot be derived at this boundary.
        transform = transform.issued_for(req.case_id)

        log_event(
            logger,
            "coregistration_completed",
            service=SERVICE_NAME,
            case_id=req.case_id,
            hfi_size=f"{hfi.width}x{hfi.height}",
            lfi_size=f"{lfi.width}x{lfi.height}",
            transform=transform.as_payload(),
            quality_metric=None,
            outcome="accepted",
        )

        return json_response(coregister_response(req.case_id, transform), 200)

    return app


def main() -> None:
    app = build_app()
    serve(app, logger, SERVICE_NAME, port_from_env(PORT_ENV_VAR, DEFAULT_PORT))


if __name__ == "__main__":
    main()
