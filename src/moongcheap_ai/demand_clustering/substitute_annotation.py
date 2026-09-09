"""Compatibility imports for the separate substitute-product review app.

New code should import from demand_clustering.evaluation.substitute_annotation.
Runtime entrypoints must not import this module.
"""

from .evaluation.substitute_annotation import (
    GOLD_LABELS,
    REASON_CODES,
    AnnotationValidationError,
    SubstituteAnnotationStore,
    dataset_fingerprint,
    load_pair_frame,
)

__all__ = [
    "GOLD_LABELS",
    "REASON_CODES",
    "AnnotationValidationError",
    "SubstituteAnnotationStore",
    "dataset_fingerprint",
    "load_pair_frame",
]
