"""Scaffold smoke tests — verify package is importable and config loads."""


def test_repolens_importable():
    import repolens

    assert repolens.__version__ == "0.1.0"


def test_config_importable():
    from repolens import config  # noqa: F401
