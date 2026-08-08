"""Narration-led footage video builder.

The package mirrors the processing pipeline: inputs, speech alignment,
segmentation, footage analysis, scoring, optimization, effects, audio mixing,
and export/reporting.
"""

from .pipeline import run_pipeline

__all__ = ["run_pipeline"]
