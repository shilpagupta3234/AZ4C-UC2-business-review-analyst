"""Settings: .env loading and empty values."""

from app import config


def test_env_file_does_not_override_existing_variables(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nUC2_TEST_A=from_file\nUC2_TEST_B=from_file\n", encoding="utf-8")
    monkeypatch.setenv("UC2_TEST_A", "already_set")
    monkeypatch.delenv("UC2_TEST_B", raising=False)
    config.load_env_file(env)
    assert config.os.environ["UC2_TEST_A"] == "already_set"
    assert config.os.environ["UC2_TEST_B"] == "from_file"


def test_empty_path_setting_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv("UC2_TEST_DIR", "")
    assert config._path_setting("UC2_TEST_DIR", tmp_path) == tmp_path.resolve()


def test_path_setting_used_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("UC2_TEST_DIR", str(tmp_path / "x"))
    assert config._path_setting("UC2_TEST_DIR", tmp_path) == (tmp_path / "x").resolve()
