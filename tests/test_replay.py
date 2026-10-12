"""Local transcript finalization and recovery integration tests."""
from datetime import datetime
from pathlib import Path
import socket
import threading

import pytest

import zoom_config
import zoom_engine
import zoom_notes
from zoom_engine import EngineState, ZoomEngine


@pytest.fixture
def capture(tmp_path, monkeypatch):
    cfg = zoom_config.ZoomNotesConfig(transcripts_dir=str(tmp_path / "Transcripts"))
    monkeypatch.setattr(zoom_engine, "get_config", lambda: cfg)
    monkeypatch.setattr(zoom_notes, "get_config", lambda: cfg)
    monkeypatch.setattr(zoom_notes, "_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(zoom_engine, "find_origin_dir", lambda: None)
    engine = ZoomEngine()
    monkeypatch.setattr(engine, "_resolve_wal", lambda *args: None)
    monkeypatch.setattr(engine, "_derive_meeting_title", lambda *args: "Weekly Sync")
    events = []
    monkeypatch.setattr(zoom_engine, "emit", events.append)
    entry = {
        "msg_id": "first", "meeting_id": "meeting_A", "speaker": "Alice",
        "timestamp": datetime.now().strftime("%H:%M:%S"), "text": "Ship the update tomorrow.",
    }
    engine._accumulated = {"first": entry}
    engine._write_tracking(meeting_id="meeting_A", session_mtime=1000)
    zoom_notes.persist_accumulator("meeting_A", engine._accumulated)
    return engine, cfg, events, entry


def test_completion_saves_short_transcript_without_keys_or_network(capture, monkeypatch):
    engine, cfg, events, entry = capture
    def no_network(*args, **kwargs):
        raise AssertionError("Saving a transcript must not open a network connection")
    monkeypatch.setattr(socket, "create_connection", no_network)
    engine._trigger_save(Path("unused"), cfg)
    assert engine._saving_lock.acquire(timeout=5)
    engine._saving_lock.release()
    files = list(cfg.transcripts_path.rglob("*.md"))
    assert len(files) == 1
    body = files[0].read_text()
    assert "Ship the update tomorrow." in body
    assert "Alice" in body
    assert "meeting_id: meeting_A" in body
    assert "\nnote:" not in body
    assert engine._get_state() == EngineState.IDLE
    assert zoom_notes.load_persisted_accumulator("meeting_A") is None
    done = next(e for e in events if e["event"] == "done")
    assert done["path"] == done["transcript_path"] == str(files[0])
    assert not list(cfg.transcripts_path.parent.rglob("Notes/*.md"))


def test_unknown_speaker_is_still_saved(capture):
    engine, cfg, events, entry = capture
    entry["speaker"] = "Unknown"
    engine._save_transcript(Path("unused"), cfg)
    assert "Unknown" in next(cfg.transcripts_path.rglob("*.md")).read_text()


def test_disk_failure_preserves_capture_and_retry_saves_transcript(capture, monkeypatch):
    engine, cfg, events, entry = capture
    real_save = zoom_engine.save_transcript_only
    def deny_write(*args, **kwargs):
        raise PermissionError("Output folder is not writable")
    monkeypatch.setattr(zoom_engine, "save_transcript_only", deny_write)
    engine._trigger_save(Path("unused"), cfg)
    assert engine._saving_lock.acquire(timeout=5)
    engine._saving_lock.release()
    assert engine._last_run_save_failed
    assert zoom_notes.load_persisted_accumulator("meeting_A")
    assert any(e["event"] == "transcript_failed" for e in events)
    assert engine._get_state() == EngineState.IDLE
    monkeypatch.setattr(zoom_engine, "save_transcript_only", real_save)
    engine._trigger_retry("meeting_A")
    assert engine._saving_lock.acquire(timeout=5)
    engine._saving_lock.release()
    assert len(list(cfg.transcripts_path.rglob("*.md"))) == 1
    assert zoom_notes.load_persisted_accumulator("meeting_A") is None
    assert engine._last_failed_meeting is None


def test_recovery_saves_transcript_without_pausing_live_capture(capture):
    engine, cfg, events, entry = capture
    engine._set_state(EngineState.ACTIVE)
    engine._trigger_retry("meeting_A")
    assert engine._saving_lock.acquire(timeout=5)
    engine._saving_lock.release()
    assert engine._get_state() == EngineState.ACTIVE
    assert next(e for e in events if e["event"] == "done")["background"] is True
    assert "Ship the update" in next(cfg.transcripts_path.rglob("*.md")).read_text()


def test_cancelled_save_does_not_write_and_keeps_recovery_snapshot(capture):
    engine, cfg, events, entry = capture
    engine._cancel_event.set()
    engine._save_transcript(Path("unused"), cfg)
    assert not list(cfg.transcripts_path.rglob("*.md"))
    assert zoom_notes.load_persisted_accumulator("meeting_A")
    assert any(e["event"] == "transcript_failed" for e in events)


def test_cli_save_and_dry_run_use_the_same_transcript_writer(tmp_path, monkeypatch, capsys):
    cfg = zoom_config.ZoomNotesConfig(transcripts_dir=str(tmp_path / "Transcripts"))
    wal = tmp_path / "transcript.sqlite3-wal"
    wal.write_bytes(b"test")
    entry = {"speaker": "Alice", "timestamp": "11:00:00", "text": "Keep this verbatim.", "msg_id": "1", "meeting_id": "A"}
    monkeypatch.setattr(zoom_notes, "get_config", lambda: cfg)
    monkeypatch.setattr(zoom_notes, "find_wal", lambda *args, **kwargs: wal)
    monkeypatch.setattr(zoom_notes, "detect_active_meeting_id", lambda *args: "A")
    monkeypatch.setattr(zoom_notes, "parse_transcript", lambda *args, **kwargs: [entry])
    monkeypatch.setattr(zoom_notes, "read_calendar_title", lambda *args: "Test Meeting")
    zoom_notes.cmd_save(tmp_path, dry_run=True)
    assert "Keep this verbatim." in capsys.readouterr().out
    assert not cfg.transcripts_path.exists()
    zoom_notes.cmd_save(tmp_path)
    assert "Keep this verbatim." in next(cfg.transcripts_path.rglob("*.md")).read_text()


def test_legacy_model_settings_are_ignored_and_output_is_preserved():
    cfg = zoom_config._config_from_dict({
        "llm_provider": "openai", "llm_model": "old-model", "system_prompt": "old prompt",
        "notes_dir": "/unused", "openai_base_url": "https://invalid.test",
        "transcripts_dir": "/existing/transcripts", "subfolder_pattern": "month",
    })
    assert cfg.transcripts_dir == "/existing/transcripts"
    assert cfg.subfolder_pattern == "month"
    assert not hasattr(cfg, "llm_provider")
    assert not hasattr(zoom_config, "get_api_key")
    assert not hasattr(zoom_notes, "summarize")


def test_custom_frontmatter_moves_to_transcripts():
    cfg = zoom_config.ZoomNotesConfig(custom_frontmatter_properties=[{"key": "project", "value": "Platform"}])
    body = zoom_notes.build_transcript_content("Speech", "Sync", "2026-10-12", cfg, meeting_id="A")
    assert "project: Platform" in body
    assert "\nnote:" not in body
