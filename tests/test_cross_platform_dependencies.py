from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_uvloop_is_not_installed_on_windows():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert '"uvloop>=0.22.1; sys_platform != \'win32\'"' in pyproject
    assert "uvloop==0.22.1 ; sys_platform != 'win32'" in requirements
