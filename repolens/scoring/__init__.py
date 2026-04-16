"""Importance scoring for classified files.

This package owns the numeric importance score (0.0–1.0) that drives
greedy file inclusion in the context packager.  See DESIGN.md §2.3.
"""

from repolens.scoring.scorer import score_file

__all__ = ["score_file"]
