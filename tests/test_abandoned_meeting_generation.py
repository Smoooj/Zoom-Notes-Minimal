"""Regression tests for the 2026-05-04 AEO GA back-to-back meeting bug.

The incident:
  1:31 PM   AEO GA started (engine flipped IDLE -> ACTIVE).
  ~2:00 PM  AEO GA ended; user joined Nick / Marissa immediately.
  2:01:56   Engine detected the new meeting_id and ran "Case B"
            (active_reevaluation): cleared the in-memory accumulator
            AND deleted AEO GA's persisted on-disk snapshot, throwing
            away ~30 minutes of real meeting transcript content.
  2:24:39   Nick / Marissa idled out, generated a normal note.
  Result:   AEO GA was never saved as a note. Transcript bytes were
            checkpointed away by Zoom shortly after; recovery from
            local disk was not possible.

The fix:
  When Case B fires with a "real-looking" abandoned accumulator
  (>= 5 entries with at least one non-Unknown speaker), snapshot it
  and kick off a background generation worker that runs the full
  three-stage pipeline (save transcript, run LLM, save note) for the
  abandoned meeting BEFORE the in-memory accumulator is cleared.

These tests guard each piece of that fix:
  - The threshold helper distinguishes real meetings from misdetections.
  - Case B correctly snapshots and dispatches when the threshold passes.
  - Case B falls back to the original delete-only behavior when below.
  - The generation worker actually saves transcript + note to disk.
  - The worker does NOT freeze the engine main loop (state stays ACTIVE).
"""
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

import zoom_engine
import zoom_notes
from zoom_engine import EngineState, ZoomEngine


# ── Fixtures (mirror test_back_to_back_meetings.py) ──────────────────────


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    cache = tmp_path / "zoom-notes-cache"
    monkeypatch.setattr(zoom_notes, "_CACHE_DIR", cache)
    yield cache


@pytest.fixture
def fake_origin(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    return origin


@pytest.fixture
def synthetic_wal(tmp_path):
    wal = tmp_path / "synthetic.sqlite3-wal"
    wal.write_bytes(b"\x00" * 4096)
    return wal


@pytest.fixture
def isolated_vault(tmp_path, monkeypatch):
    """Redirect output dirs to tmpdir so save functions don't touch the
    real vault. Mirrors the fixture in test_back_to_back_meetings.py."""
    notes_dir = tmp_path / "vault" / "Notes"
    transcripts_dir = tmp_path / "vault" / "Transcripts"
    notes_dir.mkdir(parents=True)
    transcripts_dir.mkdir(parents=True)

    real_get_config = zoom_notes.get_config

    def fake_get_config():
        cfg = real_get_config()
        cfg.notes_dir = str(notes_dir)
        cfg.transcripts_dir = str(transcripts_dir)
        return cfg

    monkeypatch.setattr(zoom_notes, "get_config", fake_get_config)
    monkeypatch.setattr(zoom_engine, "get_config", fake_get_config)
    yield {"notes": notes_dir, "transcripts": transcripts_dir}


def _make_entry(msg_id: str, text: str, *, meeting_id: str,
                speaker: str = "Test User", timestamp: str = "12:00:00") -> dict:
    return {
        "msg_id": msg_id,
        "text": text,
        "speaker": speaker,
        "timestamp": timestamp,
        "meeting_id": meeting_id,
    }


def _set_wal_size(wal: Path, size: int) -> None:
    with open(wal, "r+b") as f:
        f.truncate(size)


def _drive_tick(engine: ZoomEngine, origin: Path, cfg, *, wal: Path,
                mtime: float, size: int, entries: list[dict],
                detected_meeting_id: str | None) -> None:
    _set_wal_size(wal, size)
    os.utime(wal, (mtime, mtime))
    with patch.object(zoom_engine, "find_wal", return_value=wal), \
         patch.object(zoom_engine, "parse_transcript", return_value=entries), \
         patch.object(zoom_engine, "detect_active_meeting_id",
                      return_value=detected_meeting_id):
        engine._poll_once(origin, cfg, idle_threshold=cfg.idle_threshold_secs)


def _make_realistic_accumulator(meeting_id: str, count: int = 6) -> dict:
    """Build a snapshot that looks like a real (back-to-back) meeting:
    multiple entries, real speakers, sequential timestamps."""
    speakers = ["Alice", "Bob", "Carol"]
    return {
        f"msg-{i}": _make_entry(
            f"msg-{i}",
            f"Utterance number {i}.",
            meeting_id=meeting_id,
            speaker=speakers[i % len(speakers)],
            timestamp=f"13:3{i}:00",
        )
        for i in range(count)
    }


# ── Threshold helper ──────────────────────────────────────────────────────


class TestAbandonedLooksReal:
    """The gate between back-to-back-meeting (generate) and
    misidentification (discard). False positives cost LLM calls; false
    negatives lose data. Heuristic must correctly classify both."""

    def test_real_meeting_passes(self):
        snap = _make_realistic_accumulator("aeo-ga", count=6)
        assert ZoomEngine._abandoned_looks_real(snap) is True

    def test_too_few_entries_fails(self):
        snap = _make_realistic_accumulator("aeo-ga", count=3)
        assert ZoomEngine._abandoned_looks_real(snap) is False

    def test_only_unknown_speakers_fails(self):
        snap = {
            f"msg-{i}": _make_entry(
                f"msg-{i}", f"text {i}", meeting_id="x", speaker="Unknown",
                timestamp=f"12:0{i}:00",
            )
            for i in range(8)
        }
        assert ZoomEngine._abandoned_looks_real(snap) is False

    def test_empty_snapshot_fails(self):
        assert ZoomEngine._abandoned_looks_real({}) is False

    def test_at_least_one_real_speaker_at_threshold_passes(self):
        # Exactly 5 entries, only 1 with a real speaker — boundary case.
        snap = {
            f"msg-{i}": _make_entry(
                f"msg-{i}", f"text {i}", meeting_id="x",
                speaker=("Alice" if i == 0 else "Unknown"),
                timestamp=f"12:0{i}:00",
            )
            for i in range(5)
        }
        assert ZoomEngine._abandoned_looks_real(snap) is True


# ── Cross-meeting snapshot inflation ─────────────────────────────────────


class TestAbandonedGenerationMixedMeetingIds:
    """Regression: when entries from the NEXT meeting inflate the snapshot
    count above the _abandoned_looks_real threshold, the abandoned meeting's
    filtered entries may still be too few to warrant a note.

    Scenario (observed 2026-05-20): meeting A (Michael, 1 entry at 14:55)
    was being tracked. When meeting B started, the engine accumulated entries
    from B before Case B fired. The full snapshot had 5+ entries (threshold
    passes), but after filtering to meeting A's id only 3 entries remained.
    The abandoned generation ran and produced a near-empty, misleading note.

    The fix: inside _trigger_abandoned_save the worker re-runs
    _abandoned_looks_real on the *filtered* entries and bails out if they
    are below threshold.
    """

    def _make_snapshot_for_meeting(self, meeting_id: str, count: int, prefix: str) -> dict:
        """Like _make_realistic_accumulator but with a caller-supplied key prefix
        to avoid collisions when merging two snapshots in the same dict."""
        speakers = ["Alice", "Bob", "Carol"]
        return {
            f"{prefix}-{i}": _make_entry(
                f"{prefix}-{i}",
                f"Utterance {i}.",
                meeting_id=meeting_id,
                speaker=speakers[i % len(speakers)],
                timestamp=f"13:3{i}:00",
            )
            for i in range(count)
        }

    def test_no_generation_when_filtered_count_below_threshold(
        self, isolated_cache, isolated_vault, monkeypatch
    ):
        """If only meeting-A entries are below threshold but total snapshot
        is above it, the worker must bail out without saving a transcript."""
        import zoom_engine as ze

        seen_saves = []
        monkeypatch.setattr(ZoomEngine, "_write_transcript", lambda *a, **kw: seen_saves.append(1) or Path("transcript.md"))

        engine = ZoomEngine()

        # 3 entries for the abandoned meeting A (below threshold of 5)
        snap_a = self._make_snapshot_for_meeting("meeting-A-AA", count=3, prefix="a")
        # 4 entries for the next meeting B (inflating the total to 7)
        snap_b = self._make_snapshot_for_meeting("meeting-B-BB", count=4, prefix="b")
        mixed_snapshot = {**snap_a, **snap_b}

        assert len(mixed_snapshot) == 7
        assert ZoomEngine._abandoned_looks_real(mixed_snapshot) is True  # total passes
        # But only 3 entries belong to meeting A
        assert ZoomEngine._abandoned_looks_real(snap_a) is False  # A-only fails

        monkeypatch.setattr(threading.Thread, "start", lambda worker: worker.run())
        engine._trigger_abandoned_save("meeting-A-AA", mixed_snapshot)

        # Wait for the worker to finish (it holds the lock while running)
        assert engine._saving_lock.acquire(timeout=5.0), "worker never released lock"
        engine._saving_lock.release()

        assert seen_saves == [], (
            "_trigger_abandoned_save must not save a transcript when "
            "filtered entries are below threshold"
        )

    def test_generation_proceeds_when_filtered_count_meets_threshold(
        self, isolated_cache, isolated_vault, monkeypatch
    ):
        """If the abandoned meeting's own filtered entries meet threshold,
        generation still runs even if the total snapshot is mixed."""
        import zoom_engine as ze

        seen_saves = []
        monkeypatch.setattr(ZoomEngine, "_write_transcript", lambda *a, **kw: seen_saves.append(1) or Path("transcript.md"))
        monkeypatch.setattr(ze, "find_origin_dir", lambda: None)

        engine = ZoomEngine()

        # 6 entries for meeting A (above threshold on its own)
        snap_a = self._make_snapshot_for_meeting("meeting-A-BB", count=6, prefix="a")
        # 4 entries for meeting B (extra noise in snapshot)
        snap_b = self._make_snapshot_for_meeting("meeting-B-BB", count=4, prefix="b")
        mixed_snapshot = {**snap_a, **snap_b}

        monkeypatch.setattr(threading.Thread, "start", lambda worker: worker.run())
        engine._trigger_abandoned_save("meeting-A-BB", mixed_snapshot)

        assert engine._saving_lock.acquire(timeout=5.0), "worker never released lock"
        engine._saving_lock.release()

        assert seen_saves == [1], (
            "_trigger_abandoned_save must save a transcript when "
            "filtered entries are above threshold"
        )


# ── Case B dispatch ───────────────────────────────────────────────────────


class TestCaseBDispatch:
    """Case B in `_poll_once` must snapshot + dispatch when the abandoned
    accumulator looks real, and fall back to delete-only when it doesn't."""

    def test_case_b_defers_then_fires_when_new_meeting_proves_real(
        self, fake_origin, synthetic_wal, isolated_cache, isolated_vault
    ):
        """The 2026-06-30 single-meeting-flap fix changed Case B from
        generate-immediately to defer-until-proven. When meeting B is detected,
        meeting A's note must NOT fire yet — it's parked in `_pending_abandoned`.
        Only once meeting B accumulates real content of its own (proving a
        genuine back-to-back boundary, not an ID flap) does A's note fire.
        """
        engine = ZoomEngine()
        cfg = engine._get_cfg()

        # Tick 1: anchor at meeting A.
        _drive_tick(
            engine, fake_origin, cfg, wal=synthetic_wal,
            mtime=1000.0, size=4096, entries=[],
            detected_meeting_id="MEETING-A==",
        )
        # Tick 2: flip to ACTIVE for meeting A with a populated accumulator.
        a_entries = list(_make_realistic_accumulator("MEETING-A==", count=6).values())
        _drive_tick(
            engine, fake_origin, cfg, wal=synthetic_wal,
            mtime=1005.0, size=8192, entries=a_entries,
            detected_meeting_id="MEETING-A==",
        )
        with engine._accumulated_lock:
            pre_count = len(engine._accumulated)
        assert pre_count >= 5, "fixture sanity: accumulator must have meeting A's entries"

        # Tick 3: Case B — meeting B detected with only a couple of entries.
        # Generation must NOT fire (could be a flap); A is parked pending.
        b_entries_small = list(_make_realistic_accumulator("MEETING-B==", count=2).values())
        with patch.object(ZoomEngine, "_trigger_abandoned_save") as mock_dispatch:
            _drive_tick(
                engine, fake_origin, cfg, wal=synthetic_wal,
                mtime=1010.0, size=12288, entries=b_entries_small,
                detected_meeting_id="MEETING-B==",
            )
            mock_dispatch.assert_not_called()

        assert engine._pending_abandoned is not None, "meeting A must be parked"
        assert engine._pending_abandoned["meeting_id"] == "MEETING-A=="
        parked = engine._pending_abandoned["snapshot"]
        assert len(parked) >= 5
        assert all(e["meeting_id"] == "MEETING-A==" for e in parked.values())

        # Tick 4: meeting B accumulates real content of its own — a genuine
        # back-to-back boundary. Now A's deferred note fires, exactly once.
        b_entries_full = list(_make_realistic_accumulator("MEETING-B==", count=6).values())
        with patch.object(ZoomEngine, "_trigger_abandoned_save") as mock_dispatch:
            _drive_tick(
                engine, fake_origin, cfg, wal=synthetic_wal,
                mtime=1015.0, size=16384, entries=b_entries_full,
                detected_meeting_id="MEETING-B==",
            )
            mock_dispatch.assert_called_once()
            args = mock_dispatch.call_args[0]
            assert args[0] == "MEETING-A==", (
                f"expected dispatch for abandoned meeting A, got {args[0]}"
            )
            snapshot = args[1]
            assert len(snapshot) >= 5
            assert all(e["meeting_id"] == "MEETING-A==" for e in snapshot.values())

        assert engine._pending_abandoned is None, "pending must clear after firing"

        # The new meeting's accumulator holds only meeting B's data.
        with engine._accumulated_lock:
            ids_after = {e.get("meeting_id") for e in engine._accumulated.values()}
        assert ids_after <= {"MEETING-B=="}, (
            f"new meeting's accumulator polluted with abandoned data: {ids_after}"
        )

    def test_case_b_flap_back_restores_without_generating(
        self, fake_origin, synthetic_wal, isolated_cache, isolated_vault
    ):
        """The core 2026-06-30 fix: a single meeting whose ID oscillates
        between two values must NOT generate a premature note. When the score
        swings A -> B (B never proves real) -> A, the flap-back guard restores
        meeting A and discards the phantom B, generating nothing.
        """
        engine = ZoomEngine()
        cfg = engine._get_cfg()

        # Anchor + populate meeting A.
        _drive_tick(
            engine, fake_origin, cfg, wal=synthetic_wal,
            mtime=1000.0, size=4096, entries=[],
            detected_meeting_id="MEETING-A==",
        )
        a_entries = list(_make_realistic_accumulator("MEETING-A==", count=6).values())
        _drive_tick(
            engine, fake_origin, cfg, wal=synthetic_wal,
            mtime=1005.0, size=8192, entries=a_entries,
            detected_meeting_id="MEETING-A==",
        )

        with patch.object(ZoomEngine, "_trigger_abandoned_save") as mock_dispatch:
            # Flip to phantom B (1 entry) — A parked, nothing generated.
            b_entries = list(_make_realistic_accumulator("MEETING-B==", count=1).values())
            _drive_tick(
                engine, fake_origin, cfg, wal=synthetic_wal,
                mtime=1010.0, size=12288, entries=b_entries,
                detected_meeting_id="MEETING-B==",
            )
            assert engine._pending_abandoned is not None

            # Score swings back to A before B ever became real → flap-back.
            _drive_tick(
                engine, fake_origin, cfg, wal=synthetic_wal,
                mtime=1015.0, size=16384, entries=a_entries,
                detected_meeting_id="MEETING-A==",
            )
            mock_dispatch.assert_not_called()

        assert engine._pending_abandoned is None, "flap-back must clear pending"
        _, _, _, tracked = engine._read_tracking()
        assert tracked == "MEETING-A==", "flap-back must restore meeting A as tracked"
        with engine._accumulated_lock:
            restored_ids = {e.get("meeting_id") for e in engine._accumulated.values()}
        assert "MEETING-A==" in restored_ids, "meeting A's transcript must be restored"

    def test_case_b_carries_forward_new_meetings_opening_lines(
        self, fake_origin, synthetic_wal, isolated_cache, isolated_vault
    ):
        """The 2026-06-18 data-loss fix: when Case B switches to meeting B, the
        opening lines of B already captured during the overlap window (while
        tracking was still on A) must be carried forward and persisted to disk
        — NOT wiped to empty. Wiping was only safe because the next WAL parse
        re-adds them; if a Zoom checkpoint flushes the WAL in that window
        (simulated here by an empty parse on the switch tick), the old behavior
        lost B's opening utterances permanently.
        """
        engine = ZoomEngine()
        cfg = engine._get_cfg()

        # Anchor + populate meeting A.
        _drive_tick(
            engine, fake_origin, cfg, wal=synthetic_wal,
            mtime=1000.0, size=4096, entries=[],
            detected_meeting_id="MEETING-A==",
        )
        a_entries = list(_make_realistic_accumulator("MEETING-A==", count=6).values())
        _drive_tick(
            engine, fake_origin, cfg, wal=synthetic_wal,
            mtime=1005.0, size=8192, entries=a_entries,
            detected_meeting_id="MEETING-A==",
        )

        # Overlap tick: B's opening lines appear in the WAL while detection
        # still scores A as active. They accumulate tagged to B.
        b_entries = [
            _make_entry(f"b-{i}", f"new meeting opening line {i}",
                        meeting_id="MEETING-B==", speaker="Dave",
                        timestamp=f"14:0{i}:00")
            for i in range(3)
        ]
        _drive_tick(
            engine, fake_origin, cfg, wal=synthetic_wal,
            mtime=1010.0, size=12288, entries=a_entries + b_entries,
            detected_meeting_id="MEETING-A==",
        )
        with engine._accumulated_lock:
            b_in_acc = [e for e in engine._accumulated.values()
                        if e.get("meeting_id") == "MEETING-B=="]
        assert len(b_in_acc) == 3, "fixture sanity: B's opening lines must be present pre-switch"

        # Switch tick: detection flips to B, AND the WAL has been checkpointed
        # (empty parse) so B's opening lines are NO LONGER recoverable from the
        # WAL. Patch abandoned-generation so we don't hit the network.
        with patch.object(ZoomEngine, "_trigger_abandoned_save"):
            _drive_tick(
                engine, fake_origin, cfg, wal=synthetic_wal,
                mtime=1015.0, size=16384, entries=[],
                detected_meeting_id="MEETING-B==",
            )

        # B's opening lines survived in memory (carried, not wiped).
        with engine._accumulated_lock:
            ids_after = {e.get("meeting_id") for e in engine._accumulated.values()}
            carried = [e for e in engine._accumulated.values()
                       if e.get("meeting_id") == "MEETING-B=="]
        assert ids_after == {"MEETING-B=="}, f"unexpected accumulator ids: {ids_after}"
        assert len(carried) == 3, (
            "B's opening lines were lost on the Case B switch — they should "
            "have been carried forward when the WAL parse came back empty."
        )

        # And they were persisted to disk under B's slug (durable before the
        # next change tick).
        persisted = zoom_notes.load_persisted_accumulator("MEETING-B==")
        assert persisted is not None and len(persisted) == 3, (
            f"B's opening lines not persisted under its own slug: {persisted!r}"
        )

    def test_case_b_skips_generation_when_below_threshold(
        self, fake_origin, synthetic_wal, isolated_cache, isolated_vault
    ):
        """Misidentification path: the previous tracked meeting only had
        2 entries (briefly mistaken for active before scoring corrected).
        Should NOT trigger an LLM call — discard like the original behavior."""
        engine = ZoomEngine()
        cfg = engine._get_cfg()

        _drive_tick(
            engine, fake_origin, cfg, wal=synthetic_wal,
            mtime=1000.0, size=4096, entries=[],
            detected_meeting_id="MIS-IDENTIFIED==",
        )
        a_entries = list(_make_realistic_accumulator("MIS-IDENTIFIED==", count=2).values())
        _drive_tick(
            engine, fake_origin, cfg, wal=synthetic_wal,
            mtime=1005.0, size=8192, entries=a_entries,
            detected_meeting_id="MIS-IDENTIFIED==",
        )

        b_entries = list(_make_realistic_accumulator("REAL-MEETING==", count=2).values())
        with patch.object(ZoomEngine, "_trigger_abandoned_save") as mock_dispatch:
            _drive_tick(
                engine, fake_origin, cfg, wal=synthetic_wal,
                mtime=1010.0, size=12288, entries=b_entries,
                detected_meeting_id="REAL-MEETING==",
            )
            mock_dispatch.assert_not_called()


# ── Worker behavior ───────────────────────────────────────────────────────


class TestAbandonedTranscriptSaving:
    def test_back_to_back_saves_both_transcripts_without_pausing_capture(self, isolated_cache, isolated_vault, monkeypatch):
        engine = ZoomEngine()
        engine._set_state(EngineState.ACTIVE)
        monkeypatch.setattr(zoom_engine, "find_origin_dir", lambda: None)
        real_save = engine._write_transcript
        entered, release = threading.Event(), threading.Event()
        completed = []
        def gated_save(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return real_save(*args, **kwargs)
        monkeypatch.setattr(engine, "_write_transcript", gated_save)
        real_delete = zoom_engine.delete_persisted_accumulator
        def cleanup(mid):
            real_delete(mid)
            completed.append(mid)
        monkeypatch.setattr(zoom_engine, "delete_persisted_accumulator", cleanup)
        engine._trigger_abandoned_save("A==", _make_realistic_accumulator("A==", count=8))
        assert entered.wait(5)
        assert engine._get_state() == EngineState.ACTIVE
        engine._trigger_abandoned_save("B==", _make_realistic_accumulator("B==", count=8))
        release.set()
        import time
        deadline = time.monotonic() + 5
        while len(completed) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert sorted(completed) == ["A==", "B=="]
        assert engine._get_state() == EngineState.ACTIVE
        files = list(Path(isolated_vault["transcripts"]).rglob("*.md"))
        assert len(files) == 2
        assert {zoom_notes._read_existing_meeting_id(p) for p in files} == {"A==", "B=="}
        assert all("Utterance" in p.read_text() or "utterance" in p.read_text() for p in files)
