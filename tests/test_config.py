import json

from local_ai_manager import config
from local_ai_manager.config import Config, get_config, settings_path


def test_mandatory_defaults_are_off():
    c = Config()
    assert c.gaming_mode_enabled is False
    assert c.start_with_windows is False
    assert c.auto_start_last_model is False
    assert c.service_control_as_root is False
    assert c.keep_alive_minutes == 30


def test_default_url_is_loopback():
    assert Config().ollama_base_url.startswith("http://127.0.0.1:")


def test_settings_path_uses_override(isolated_settings):
    assert settings_path() == isolated_settings / "settings.json"


def test_settings_path_defaults_to_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCAL_AI_MANAGER_CONFIG_DIR")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert settings_path() == tmp_path / "LocalAIManager" / "settings.json"


def test_import_and_load_do_not_create_files(isolated_settings):
    Config.load()
    assert not isolated_settings.exists()


def test_save_load_round_trip(isolated_settings):
    c = Config(gaming_mode_enabled=True, last_model="qwen3.8:27b", keep_alive_minutes=45)
    assert c.save() is True
    data = json.loads((isolated_settings / "settings.json").read_text(encoding="utf-8"))
    assert data["last_model"] == "qwen3.8:27b"
    loaded = Config.load()
    assert loaded.gaming_mode_enabled is True
    assert loaded.keep_alive_minutes == 45
    assert not list(isolated_settings.glob("*.tmp"))


def test_corrupt_json_falls_back_to_defaults(isolated_settings):
    isolated_settings.mkdir(parents=True)
    (isolated_settings / "settings.json").write_text("{not json", encoding="utf-8")
    assert Config.load() == Config()


def test_non_object_json_falls_back_to_defaults(isolated_settings):
    isolated_settings.mkdir(parents=True)
    (isolated_settings / "settings.json").write_text("[1, 2]", encoding="utf-8")
    assert Config.load() == Config()


def test_unknown_keys_and_wrong_types_are_ignored(isolated_settings):
    isolated_settings.mkdir(parents=True)
    (isolated_settings / "settings.json").write_text(json.dumps({
        "unknown_key": 1,
        "gaming_mode_enabled": "yes",     # wrong type
        "keep_alive_minutes": True,       # bool is not int here
        "last_model": "gpt-oss:20b",      # valid
    }), encoding="utf-8")
    c = Config.load()
    assert c.gaming_mode_enabled is False
    assert c.keep_alive_minutes == 30
    assert c.last_model == "gpt-oss:20b"


def test_out_of_range_values_are_clamped():
    c = Config.from_dict({"gpu_poll_interval_ms": 1, "keep_alive_minutes": 999999})
    assert c.gpu_poll_interval_ms == 500
    assert c.keep_alive_minutes == 1440


def test_legacy_config_json_is_read(isolated_settings):
    isolated_settings.mkdir(parents=True)
    (isolated_settings / "config.json").write_text(
        json.dumps({"gpu_poll_interval_ms": 3000, "preferred_distro": ""}), encoding="utf-8")
    assert Config.load().gpu_poll_interval_ms == 3000


def test_save_failure_returns_false(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert Config().save(blocker / "sub" / "settings.json") is False


def test_get_config_is_singleton():
    assert get_config() is get_config()
    config.reset_config_cache()
