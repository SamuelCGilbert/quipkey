import json
import sys
from pathlib import Path

import pytest

from quipkey import cli, config, paths
from quipkey.meta import APP_NAME, VERSION


@pytest.fixture
def home(tmp_path, monkeypatch):
    for var in ("APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(tmp_path / var))
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(var, str(tmp_path / var))
    return tmp_path


def test_paths_are_per_user_and_named_after_the_app(home):
    for p in (paths.config_path(), paths.state_path(), paths.log_path(), paths.models_dir()):
        assert str(p).startswith(str(home))
        assert APP_NAME in p.parts


def test_load_config_defaults_and_overrides(home):
    assert config.load_config() == config.DEFAULT_CONFIG
    path = paths.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"quantization": None, "bogus": 1}), encoding="utf-8")
    cfg = config.load_config()
    assert cfg["quantization"] is None
    assert "bogus" not in cfg


def test_bad_config_falls_back_to_defaults(home):
    path = paths.config_path()
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert config.load_config() == config.DEFAULT_CONFIG


def test_set_config_value_keeps_other_settings(home):
    path = config.ensure_config_file()
    config.set_config_value("device", "directml")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["device"] == "directml"
    assert data["model"] == config.DEFAULT_CONFIG["model"]


def test_state_roundtrip(home):
    config.save_state(mic="USB mic")
    config.save_state(welcomed=True)
    assert config.load_state() == {"mic": "USB mic", "welcomed": True}


def test_cli_version(capsys):
    cli.main(["--version"])
    assert capsys.readouterr().out.strip() == f"{APP_NAME} {VERSION}"


def test_cli_unknown_command():
    with pytest.raises(SystemExit) as e:
        cli.main(["frobnicate"])
    assert e.value.code == 2


def test_cli_client_does_not_import_heavy_modules(home, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("the socket client is Linux-only")
    import subprocess

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(home))
    code = "\n".join([
        "import sys",
        "from quipkey import cli",
        "try:",
        "    cli.main(['toggle'])",
        "except SystemExit as e:",
        "    print(e.code)",
        "print(sorted(m for m in ('numpy', 'onnxruntime', 'tkinter') if m in sys.modules))",
    ])
    src = str(Path(__file__).resolve().parent.parent / "src")
    monkeypatch.setenv("PYTHONPATH", src)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.split()
    assert out == ["1", "[]"]  # exit 1: nothing is listening; nothing heavy was imported
