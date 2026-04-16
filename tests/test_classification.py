"""Tests for repolens.classification.classifier.

Scoring tests live in :mod:`tests.test_scoring` after the scoring logic
was extracted into :mod:`repolens.scoring.scorer`.
"""

from __future__ import annotations

import pytest

from repolens.classification.classifier import classify_file


# ---------------------------------------------------------------------------
# classify_file — parametrized
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative_path, extension, expected",
    [
        # Rule 1: generated segments in path
        ("__pycache__/mod.cpython-311.pyc", ".pyc", "generated"),
        ("dist/bundle.js", ".js", "generated"),
        ("build/output.o", ".o", "generated"),
        (".git/config", "", "generated"),
        ("src/__pycache__/utils.pyc", ".pyc", "generated"),
        # Rule 2: test files
        ("tests/test_foo.py", ".py", "test"),
        ("src/test_utils.py", ".py", "test"),
        ("src/utils_test.py", ".py", "test"),
        ("app/tests/integration.py", ".py", "test"),
        # Rule 3: docs
        ("README.md", ".md", "docs"),
        ("README.rst", ".rst", "docs"),
        ("docs/guide.md", ".md", "docs"),
        ("docs/api.rst", ".rst", "docs"),
        ("docs/notes.txt", ".txt", "docs"),
        # NOT docs — .md but not in docs/ and not README
        ("src/CHANGELOG.md", ".md", "other"),
        ("src/notes.txt", ".txt", "other"),
        # Rule 4: config — explicit filenames
        ("pyproject.toml", ".toml", "config"),
        ("setup.py", ".py", "config"),
        ("setup.cfg", ".cfg", "config"),
        ("Makefile", "", "config"),
        ("Dockerfile", "", "config"),
        (".dockerignore", "", "config"),
        # Rule 4: config — config extension at root depth
        ("config.yaml", ".yaml", "config"),
        (".env", ".env", "config"),
        ("settings.json", ".json", "config"),
        ("tox.ini", ".ini", "config"),
        # NOT config at depth > 1 — .json not in CORE_EXTENSIONS, falls to other
        ("src/subpkg/settings.json", ".json", "other"),
        # Rule 5: core source
        ("repolens/classifier.py", ".py", "core"),
        ("src/index.ts", ".ts", "core"),
        ("cmd/main.go", ".go", "core"),
        ("lib/parser.rs", ".rs", "core"),
        ("app/Main.java", ".java", "core"),
        ("lib/helper.rb", ".rb", "core"),
        ("App.swift", ".swift", "core"),
        ("src/utils.c", ".c", "core"),
        ("src/parser.cpp", ".cpp", "core"),
        ("include/foo.h", ".h", "core"),
        # Rule 6: other
        ("assets/logo.png", ".png", "other"),
        ("data/sample.csv", ".csv", "other"),
        ("LICENSE", "", "other"),
    ],
)
def test_classify_file(relative_path: str, extension: str, expected: str) -> None:
    assert classify_file(relative_path, extension) == expected


# Clarify the depth>1 config-extension case explicitly
def test_classify_config_extension_depth_gt1_falls_through() -> None:
    # depth == 2 (src/subpkg/settings.json) — config rule skipped; not a core ext → other
    result = classify_file("src/subpkg/settings.json", ".json")
    assert result == "other"


def test_classify_config_extension_depth_1() -> None:
    # depth == 1 (subdir/settings.json) → config
    result = classify_file("subdir/settings.json", ".json")
    assert result == "config"
