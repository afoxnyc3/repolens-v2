"""Tests for repolens.scoring.scorer.score_file."""

from __future__ import annotations

import time

import pytest

from repolens.scoring.scorer import score_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PAST_MTIME = int(time.time()) - 30 * 86400   # 30 days ago (no recency bonus)
RECENT_MTIME = int(time.time()) - 1 * 86400  # 1 day ago (recency bonus applies)
SMALL = 1_000
LARGE = 25_000  # > 20 KB


# ---------------------------------------------------------------------------
# Back-compat re-export from classifier
# ---------------------------------------------------------------------------


def test_classifier_reexports_score_file_for_backcompat():
    """Older imports must keep working: `from ...classifier import score_file`."""
    from repolens.classification.classifier import score_file as legacy

    assert legacy is score_file


# ---------------------------------------------------------------------------
# score_file — base weights
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category, expected_base",
    [
        ("core", 1.0),
        ("config", 0.8),
        ("test", 0.6),
        ("docs", 0.5),
        ("build", 0.3),
        ("generated", 0.0),
        ("other", 0.2),
    ],
)
def test_score_base_weight_no_penalties(category: str, expected_base: float) -> None:
    """Depth=0, small file, old mtime, non-entry-point → pure base weight."""
    score = score_file("file.x", category, SMALL, PAST_MTIME)
    assert score == pytest.approx(expected_base, abs=1e-6)


def test_unknown_category_falls_back_to_0_2():
    """Unknown category yields the 'other' weight of 0.2."""
    score = score_file("weird.py", "brand-new-category", SMALL, PAST_MTIME)
    assert score == pytest.approx(0.2, abs=1e-6)


# ---------------------------------------------------------------------------
# score_file — depth penalty
# ---------------------------------------------------------------------------


def test_score_depth_penalty_shallow() -> None:
    # depth=2: penalty = 1 - 0.05*2 = 0.9; 1.0 * 0.9 = 0.9
    score = score_file("a/b/file.py", "core", SMALL, PAST_MTIME)
    assert score == pytest.approx(1.0 * 0.9, abs=1e-6)


def test_score_depth_penalty_deep_hits_floor() -> None:
    # depth=12: raw = 1 - 0.05*12 = 0.4 < 0.5 → clamped to 0.5; 1.0 * 0.5 = 0.5
    score = score_file("a/b/c/d/e/f/g/h/i/j/k/l/file.py", "core", SMALL, PAST_MTIME)
    assert score == pytest.approx(0.5, abs=1e-6)


def test_score_depth_penalty_exactly_at_floor() -> None:
    # depth=10: 1 - 0.05*10 = 0.5 → exactly at floor; 1.0 * 0.5 = 0.5
    score = score_file("a/b/c/d/e/f/g/h/i/j/file.py", "core", SMALL, PAST_MTIME)
    assert score == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# score_file — size penalty
# ---------------------------------------------------------------------------


def test_score_size_penalty_applied() -> None:
    # core, depth=0, large: 1.0 * 0.8 = 0.8
    score = score_file("big.py", "core", LARGE, PAST_MTIME)
    assert score == pytest.approx(0.8, abs=1e-6)


def test_score_size_penalty_not_applied_below_threshold() -> None:
    score = score_file("small.py", "core", 20_000, PAST_MTIME)
    assert score == pytest.approx(1.0, abs=1e-6)


def test_score_size_and_depth_combined() -> None:
    # depth=2: 1.0 * 0.9 = 0.9; large: 0.9 * 0.8 = 0.72
    score = score_file("a/b/big.py", "core", LARGE, PAST_MTIME)
    assert score == pytest.approx(0.72, abs=1e-6)


# ---------------------------------------------------------------------------
# score_file — recency bonus
# ---------------------------------------------------------------------------


def test_score_recency_bonus_applied() -> None:
    # core, depth=0, small, recent: 1.0 + 0.1 → clamped to 1.0
    score = score_file("recent.py", "core", SMALL, RECENT_MTIME)
    assert score == pytest.approx(1.0, abs=1e-6)


def test_score_recency_bonus_docs() -> None:
    # docs, depth=0, small, recent: 0.5 + 0.1 = 0.6
    score = score_file("README.md", "docs", SMALL, RECENT_MTIME)
    assert score == pytest.approx(0.6, abs=1e-6)


def test_score_no_recency_bonus_old_file() -> None:
    score = score_file("old.py", "core", SMALL, PAST_MTIME)
    assert score == pytest.approx(1.0, abs=1e-6)


def test_score_recency_boundary_just_inside() -> None:
    # exactly 7 days ago minus 1 second → should get bonus
    mtime = int(time.time()) - 7 * 86400 + 1
    score = score_file("file.py", "core", SMALL, mtime)
    assert score == pytest.approx(1.0, abs=1e-6)


def test_score_recency_boundary_just_outside() -> None:
    # exactly 7 days + 1 second ago → no bonus
    mtime = int(time.time()) - 7 * 86400 - 1
    score = score_file("file.py", "core", SMALL, mtime)
    assert score == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# score_file — entry-point boost
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", ["main.py", "app.py", "index.py", "__init__.py"])
def test_score_entry_point_boost_at_depth_0(filename: str) -> None:
    # core, depth=0, small, old: 1.0 + 0.2 → clamped 1.0
    score = score_file(filename, "core", SMALL, PAST_MTIME)
    assert score == pytest.approx(1.0, abs=1e-6)


def test_score_entry_point_boost_on_lower_base() -> None:
    # Use "other" category (base=0.2) with entry point boost: 0.2 + 0.2 = 0.4
    score = score_file("main.py", "other", SMALL, PAST_MTIME)
    assert score == pytest.approx(0.4, abs=1e-6)


def test_score_entry_point_no_boost_at_depth_1() -> None:
    # Entry point deeper than root → no boost
    score = score_file("src/main.py", "core", SMALL, PAST_MTIME)
    # depth=1: 1.0 * (1 - 0.05) = 0.95; no entry boost
    assert score == pytest.approx(0.95, abs=1e-6)


# ---------------------------------------------------------------------------
# score_file — combined interactions
# ---------------------------------------------------------------------------


def test_score_generated_stays_low_but_recency_still_applies() -> None:
    score = score_file("dist/bundle.js", "generated", LARGE, RECENT_MTIME)
    # base=0.0; depth penalty: 0.0 * 0.9 = 0.0; size: 0.0 * 0.8 = 0.0;
    # recency: min(1.0, 0.0 + 0.1) = 0.1 — recency DOES apply to generated.
    assert score == pytest.approx(0.1, abs=1e-6)


def test_score_all_penalties_combined() -> None:
    # config (0.8), depth=3 (penalty=1-0.15=0.85), large (*0.8), old mtime, non-entry
    # 0.8 * 0.85 * 0.8 = 0.544
    score = score_file("a/b/c/settings.yaml", "config", LARGE, PAST_MTIME)
    assert score == pytest.approx(0.8 * 0.85 * 0.8, abs=1e-6)


def test_score_output_bounded_0_to_1():
    """Hostile inputs: score must still land in [0, 1]."""
    score = score_file("main.py", "core", SMALL, RECENT_MTIME)
    assert 0.0 <= score <= 1.0
    score2 = score_file("a/b/c/d/e/f/g/h.py", "generated", LARGE * 10, PAST_MTIME)
    assert 0.0 <= score2 <= 1.0


def test_score_rounded_to_6_decimals():
    score = score_file("a/b/file.py", "core", LARGE, PAST_MTIME)
    assert score == round(score, 6)
