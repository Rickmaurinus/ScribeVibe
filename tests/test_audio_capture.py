"""Tests for audio_capture.py — buffer management, process_raw, zero-copy swap."""

import collections

import numpy as np
import pytest

from audio_capture import AudioRecorder, DTYPE, FALLBACK_RATE, TARGET_SAMPLE_RATE


def _make_raw(chunks, needs_resample=False, stream_rate=TARGET_SAMPLE_RATE):
    return {
        "chunks": collections.deque(chunks),
        "needs_resample": needs_resample,
        "stream_rate": stream_rate,
    }


def _col(values):
    """Make a (N, 1) float32 column array — what sounddevice provides."""
    return np.array([[v] for v in values], dtype=DTYPE)


# ── AudioRecorder.process_raw() ───────────────────────────────────────────────


class TestProcessRaw:
    def test_empty_chunks_returns_empty_float32(self):
        result = AudioRecorder.process_raw(_make_raw([]))
        assert isinstance(result, np.ndarray)
        assert result.dtype == DTYPE
        assert len(result) == 0

    def test_single_chunk_no_resample(self):
        result = AudioRecorder.process_raw(_make_raw([_col([0.1, 0.2, 0.3])]))
        np.testing.assert_array_almost_equal(result, [0.1, 0.2, 0.3])

    def test_multiple_chunks_concatenated_in_order(self):
        result = AudioRecorder.process_raw(_make_raw([_col([0.1, 0.2]), _col([0.3, 0.4])]))
        np.testing.assert_array_almost_equal(result, [0.1, 0.2, 0.3, 0.4])

    def test_result_is_flat_1d(self):
        result = AudioRecorder.process_raw(_make_raw([np.ones((100, 1), dtype=DTYPE)]))
        assert result.ndim == 1
        assert len(result) == 100

    def test_result_dtype_is_float32(self):
        result = AudioRecorder.process_raw(_make_raw([_col([1.0, 2.0])]))
        assert result.dtype == np.float32

    def test_resample_48k_to_16k_length(self):
        # 1 second at 48 kHz → should produce ~16 000 samples at 16 kHz
        chunk = np.zeros((FALLBACK_RATE, 1), dtype=DTYPE)
        raw = _make_raw([chunk], needs_resample=True, stream_rate=FALLBACK_RATE)
        result = AudioRecorder.process_raw(raw)
        assert abs(len(result) - TARGET_SAMPLE_RATE) < 200  # allow small rounding

    def test_resample_result_is_float32(self):
        chunk = np.zeros((FALLBACK_RATE, 1), dtype=DTYPE)
        raw = _make_raw([chunk], needs_resample=True, stream_rate=FALLBACK_RATE)
        result = AudioRecorder.process_raw(raw)
        assert result.dtype == np.float32

    def test_no_resample_preserves_all_samples(self):
        chunk = _col([0.1, 0.2, 0.3, 0.4, 0.5])
        result = AudioRecorder.process_raw(_make_raw([chunk], needs_resample=False))
        assert len(result) == 5

    def test_empty_after_resample_flag_is_noop(self):
        raw = _make_raw([], needs_resample=True, stream_rate=FALLBACK_RATE)
        result = AudioRecorder.process_raw(raw)
        assert len(result) == 0


# ── Recording toggle (no real mic stream) ─────────────────────────────────────


class TestRecordingToggle:
    """Tests against internal state — no sounddevice stream is opened."""

    def _recorder(self):
        r = AudioRecorder()
        r._stream = object()       # non-None prevents open_stream() from being called
        r._current_device = None
        return r

    def test_initial_state_not_capturing(self):
        r = self._recorder()
        assert not r._capturing.is_set()

    def test_start_recording_sets_capturing_flag(self):
        r = self._recorder()
        r.start_recording(device_id=None)
        assert r._capturing.is_set()

    def test_start_recording_clears_existing_buffer(self):
        r = self._recorder()
        r._buffer.append(np.zeros(10, dtype=DTYPE))
        r.start_recording(device_id=None)
        assert len(r._buffer) == 0

    def test_stop_clears_capturing_flag(self):
        r = self._recorder()
        r._capturing.set()
        r.stop_recording_raw()
        assert not r._capturing.is_set()

    def test_stop_returns_old_buffer_by_reference(self):
        r = self._recorder()
        r._capturing.set()
        r._buffer.append(_col([1.0, 2.0]))
        old_buf = r._buffer

        raw = r.stop_recording_raw()

        assert raw["chunks"] is old_buf

    def test_stop_replaces_buffer_with_fresh_deque(self):
        r = self._recorder()
        r._capturing.set()
        r._buffer.append(_col([1.0]))
        old_buf = r._buffer

        r.stop_recording_raw()

        assert r._buffer is not old_buf
        assert len(r._buffer) == 0

    def test_stop_raw_includes_metadata(self):
        r = self._recorder()
        r._needs_resample = True
        r._stream_rate = FALLBACK_RATE

        raw = r.stop_recording_raw()

        assert raw["needs_resample"] is True
        assert raw["stream_rate"] == FALLBACK_RATE

    def test_double_stop_returns_independent_buffers(self):
        """Stopping twice must not share the same buffer object."""
        r = self._recorder()
        r._capturing.set()
        r._buffer.append(_col([0.5]))

        first = r.stop_recording_raw()
        second = r.stop_recording_raw()

        assert first["chunks"] is not second["chunks"]
        assert len(first["chunks"]) == 1
        assert len(second["chunks"]) == 0

    def test_chunks_accumulated_during_capture(self):
        r = self._recorder()
        r.start_recording(device_id=None)

        chunk_a = _col([0.1, 0.2])
        chunk_b = _col([0.3])
        r._buffer.append(chunk_a.copy())
        r._buffer.append(chunk_b.copy())

        raw = r.stop_recording_raw()
        assert len(raw["chunks"]) == 2


# ── Live callback ─────────────────────────────────────────────────────────────


class TestLiveCallback:
    def test_set_callback_is_stored(self):
        r = AudioRecorder()
        fn = lambda c: None
        r.set_live_callback(fn)
        assert r._live_callback is fn

    def test_clear_callback_with_none(self):
        r = AudioRecorder()
        r.set_live_callback(lambda c: None)
        r.set_live_callback(None)
        assert r._live_callback is None
