from pathlib import Path


def test_helper_has_shell_shebang_for_direct_execution():
    helper = Path(__file__).resolve().parents[1] / "bin" / "dh-pve-ups-policy-cmd"
    assert helper.read_text(encoding="utf-8").startswith("#!/")
