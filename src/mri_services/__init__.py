"""HTTP service wrappers, one process per compute function.

Depends on `mri_core` and `mri_contract`. Nothing depends on this package; it
is the outermost layer and holds every impure concern -- sockets, JSON, base64,
logging, process lifecycle.
"""
