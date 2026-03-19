"""Tests for config.py — settings load/save/cache behaviour."""
import json
import os
import pytest
import config


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Run every test in a temp directory with a fresh Config instance."""
    monkeypatch.chdir(tmp_path)
    fresh = config.Config(settings_file=str(tmp_path / "settings.json"))
    monkeypatch.setattr(config, "_instance", fresh)


# ── load() ────────────────────────────────────────────────────────────


class TestLoad:
    def test_returns_defaults_when_no_file(self):
        result = config.load()
        assert result == config.DEFAULTS

    def test_merges_file_with_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"device_id": 5}))
        result = config.load()
        assert result["device_id"] == 5
        # Other defaults still present
        assert result["beam_size"] == config.DEFAULTS["beam_size"]
        assert result["model_size_en"] == config.DEFAULTS["model_size_en"]

    def test_file_values_override_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"beam_size": 5, "model_size_en": "medium.en"}))
        result = config.load()
        assert result["beam_size"] == 5
        assert result["model_size_en"] == "medium.en"

    def test_unknown_keys_preserved(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"custom_key": "hello"}))
        result = config.load()
        assert result["custom_key"] == "hello"

    def test_returns_copy_not_reference(self):
        a = config.load()
        b = config.load()
        a["beam_size"] = 999
        assert b["beam_size"] != 999

    def test_caches_after_first_read(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"device_id": 1}))
        first = config.load()
        # Overwrite the file — cache should still return old value
        path.write_text(json.dumps({"device_id": 99}))
        second = config.load()
        assert first["device_id"] == second["device_id"] == 1

    def test_handles_empty_json_object(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{}")
        result = config.load()
        assert result == config.DEFAULTS


# ── save() ────────────────────────────────────────────────────────────


class TestSave:
    def test_writes_to_disk(self, tmp_path):
        settings = {**config.DEFAULTS, "beam_size": 10}
        config.save(settings)
        on_disk = json.loads((tmp_path / "settings.json").read_text())
        assert on_disk["beam_size"] == 10

    def test_updates_cache(self):
        config.load()  # prime cache
        config.save({**config.DEFAULTS, "device_id": 42})
        assert config.load()["device_id"] == 42

    def test_save_then_load_roundtrip(self):
        original = {**config.DEFAULTS, "model_size_nl": "medium"}
        config.save(original)
        loaded = config.load()
        assert loaded["model_size_nl"] == "medium"


# ── set_* helpers ─────────────────────────────────────────────────────


class TestSetHelpers:
    def test_set_device(self, tmp_path):
        config.set_device(7)
        on_disk = json.loads((tmp_path / "settings.json").read_text())
        assert on_disk["device_id"] == 7
        assert config.load()["device_id"] == 7

    def test_set_device_none(self):
        config.set_device(3)
        config.set_device(None)
        assert config.load()["device_id"] is None

    def test_set_model_size_en(self, tmp_path):
        config.set_model_size_en("medium.en")
        on_disk = json.loads((tmp_path / "settings.json").read_text())
        assert on_disk["model_size_en"] == "medium.en"

    def test_set_model_size_nl(self, tmp_path):
        config.set_model_size_nl("large")
        on_disk = json.loads((tmp_path / "settings.json").read_text())
        assert on_disk["model_size_nl"] == "large"

    def test_set_preserves_other_keys(self):
        config.save({**config.DEFAULTS, "beam_size": 8})
        config.set_device(2)
        assert config.load()["beam_size"] == 8
