"""Compute core: coregistration and spatial transformation.

Depends on `mri_contract` (standard library only) and Pillow. Must never import
Flask or anything in `mri_services`: the declared direction is
`mri_services -> mri_core -> mri_contract`, so a transport defect cannot alter
a computed result.
"""
