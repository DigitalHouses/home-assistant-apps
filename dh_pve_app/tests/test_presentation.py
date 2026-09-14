import importlib.util


def test_adaptive_presentation_module_exists():
    assert importlib.util.find_spec("app.presentation") is not None
