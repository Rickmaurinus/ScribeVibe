"""Tests for output_handler.py — log writing, trimming, deletion."""
import threading
import pytest
import output_handler


@pytest.fixture(autouse=True)
def _isolate_log(tmp_path, monkeypatch):
    """Point the log file to a temp directory and reset module state."""
    log_path = str(tmp_path / "transcription_log.txt")
    monkeypatch.setattr(output_handler, "LOG_FILE", log_path)
    monkeypatch.setattr(output_handler, "_log_count", 0)
    monkeypatch.setattr(output_handler, "_log_hook", None)
    # Replace locks to avoid cross-test contention
    monkeypatch.setattr(output_handler, "_paste_lock", threading.Lock())
    monkeypatch.setattr(output_handler, "_file_lock", threading.Lock())


def _read_log() -> str:
    with open(output_handler.LOG_FILE, "r", encoding="utf-8") as f:
        return f.read()


def _read_lines() -> list[str]:
    try:
        with open(output_handler.LOG_FILE, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f if line.strip()]
    except FileNotFoundError:
        return []


# ── log_transcription() ──────────────────────────────────────────────


class TestLogTranscription:
    def test_creates_file_and_writes_entry(self):
        output_handler.log_transcription("hello world", "small.en", 1.23)
        content = _read_log()
        assert "hello world" in content
        assert "small.en" in content
        assert "1.23s" in content

    def test_entry_format(self):
        output_handler.log_transcription("test text", "base.en", 0.50)
        lines = _read_lines()
        assert len(lines) == 1
        # Format: [timestamp] [model | time] text
        assert lines[0].startswith("[")
        assert "[base.en | 0.50s]" in lines[0]
        assert lines[0].endswith("test text")

    def test_appends_multiple_entries(self):
        output_handler.log_transcription("first", "a", 1.0)
        output_handler.log_transcription("second", "b", 2.0)
        output_handler.log_transcription("third", "c", 3.0)
        lines = _read_lines()
        assert len(lines) == 3
        assert "first" in lines[0]
        assert "third" in lines[2]

    def test_empty_model_name(self):
        output_handler.log_transcription("text", "", 0.0)
        content = _read_log()
        assert "[ | 0.00s]" in content

    def test_calls_log_hook(self):
        calls = []
        output_handler.set_log_hook(lambda ts, meta, text: calls.append((ts, meta, text)))
        output_handler.log_transcription("hooked", "model", 1.0)
        assert len(calls) == 1
        assert calls[0][2] == "hooked"
        assert "model" in calls[0][1]


# ── _trim_log() ──────────────────────────────────────────────────────


class TestTrimLog:
    def test_no_trim_under_limit(self):
        for i in range(10):
            output_handler.log_transcription(f"line {i}", "m", 0.1)
        lines = _read_lines()
        assert len(lines) == 10

    def test_trims_to_max(self, monkeypatch):
        monkeypatch.setattr(output_handler, "_MAX_LOG_ENTRIES", 5)
        # Write 8 lines directly to avoid the every-50 trigger
        with open(output_handler.LOG_FILE, "w", encoding="utf-8") as f:
            for i in range(8):
                f.write(f"[2026-01-01 00:00:0{i}] [m | 0.10s] line {i}\n")
        output_handler._trim_log()
        lines = _read_lines()
        assert len(lines) == 5
        # Keeps the newest (last) entries
        assert "line 3" in lines[0]
        assert "line 7" in lines[4]

    def test_trim_no_op_when_under_limit(self, monkeypatch):
        monkeypatch.setattr(output_handler, "_MAX_LOG_ENTRIES", 100)
        output_handler.log_transcription("only one", "m", 0.1)
        output_handler._trim_log()
        lines = _read_lines()
        assert len(lines) == 1

    def test_trim_on_missing_file(self):
        # Should not raise
        output_handler._trim_log()

    def test_auto_trim_triggers_every_50(self, monkeypatch):
        monkeypatch.setattr(output_handler, "_MAX_LOG_ENTRIES", 10)
        # Write 55 entries — trim should trigger at entry 50
        for i in range(55):
            output_handler.log_transcription(f"entry {i}", "m", 0.1)
        lines = _read_lines()
        assert len(lines) <= 15  # 10 after trim + up to 5 more


# ── delete_log_entry() ───────────────────────────────────────────────


class TestDeleteLogEntry:
    def test_deletes_matching_entry(self):
        output_handler.log_transcription("keep me", "m", 1.0)
        output_handler.log_transcription("delete me", "m", 2.0)
        output_handler.log_transcription("keep me too", "m", 3.0)

        lines = _read_lines()
        assert len(lines) == 3

        # Parse the middle entry to get exact ts and meta
        # Format: [ts] [meta] text
        import re
        m = re.match(r"^\[(.+?)\] \[(.+?)\] (.+)$", lines[1])
        assert m is not None
        output_handler.delete_log_entry(m.group(1), m.group(2), m.group(3))

        remaining = _read_lines()
        assert len(remaining) == 2
        assert all("delete me" not in line for line in remaining)

    def test_deletes_only_first_match(self):
        # Write two identical entries
        output_handler.log_transcription("dupe", "m", 1.0)
        output_handler.log_transcription("dupe", "m", 1.0)
        lines = _read_lines()

        import re
        m = re.match(r"^\[(.+?)\] \[(.+?)\] (.+)$", lines[0])
        output_handler.delete_log_entry(m.group(1), m.group(2), m.group(3))

        remaining = _read_lines()
        # Only one of the two should be deleted
        assert len(remaining) == 1

    def test_no_match_leaves_file_unchanged(self):
        output_handler.log_transcription("stay", "m", 1.0)
        output_handler.delete_log_entry("9999-01-01 00:00:00", "x", "gone")
        lines = _read_lines()
        assert len(lines) == 1
        assert "stay" in lines[0]

    def test_delete_on_missing_file(self):
        # Should not raise
        output_handler.delete_log_entry("ts", "meta", "text")

    def test_delete_entry_without_meta(self):
        """Older log format: [ts] text (no meta brackets)."""
        with open(output_handler.LOG_FILE, "w", encoding="utf-8") as f:
            f.write("[2026-01-01 12:00:00] old format text\n")
        output_handler.delete_log_entry("2026-01-01 12:00:00", "", "old format text")
        remaining = _read_lines()
        assert len(remaining) == 0


# ── set_log_hook() ───────────────────────────────────────────────────


class TestSetLogHook:
    def test_set_and_clear_hook(self):
        calls = []
        output_handler.set_log_hook(lambda ts, meta, text: calls.append(text))
        output_handler.log_transcription("a", "m", 0.1)
        assert calls == ["a"]

        output_handler.set_log_hook(None)
        output_handler.log_transcription("b", "m", 0.1)
        assert calls == ["a"]  # no new call
