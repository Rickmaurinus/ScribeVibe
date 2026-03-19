"""Tests for select_mic.py — junk filtering and deduplication logic."""

from unittest.mock import patch

import pytest

from select_mic import _is_junk, get_clean_mic_list

# ── _is_junk() ────────────────────────────────────────────────────────


class TestIsJunk:
    @pytest.mark.parametrize(
        "name",
        [
            "Microsoft Sound Mapper - Input",
            "Primary Sound Capture Driver",
            "PC Speaker",
            "Stereo Mix (Realtek Audio)",
            "Something with SST",
            "Chat Mic (Chat Mic)",  # WASAPI alias
            "Headset (Headset)",  # WASAPI alias
            "@System32\\drivers\\something",
        ],
    )
    def test_junk_names_filtered(self, name):
        assert _is_junk(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "Blue Yeti Stereo",
            "Microphone (Realtek Audio)",
            "Rode NT-USB",
            "GoXLR (Chat)",  # not WASAPI alias pattern
            "USB Audio Device",
        ],
    )
    def test_valid_names_kept(self, name):
        assert _is_junk(name) is False

    def test_case_insensitive(self):
        assert _is_junk("MICROSOFT SOUND MAPPER - INPUT") is True
        assert _is_junk("stereo MIX blah") is True
        assert _is_junk("pc SPEAKER something") is True


# ── get_clean_mic_list() ─────────────────────────────────────────────


def _make_device(name, max_input_channels, hostapi=0):
    return {
        "name": name,
        "max_input_channels": max_input_channels,
        "max_output_channels": 0,
        "hostapi": hostapi,
    }


def _make_hostapis(*names):
    return [{"name": n} for n in names]


class TestGetCleanMicList:
    def test_filters_output_only_devices(self):
        devices = [
            _make_device("Speakers", 0),
            _make_device("Mic", 1),
        ]
        hostapis = _make_hostapis("MME")
        with patch("select_mic.sd") as mock_sd:
            mock_sd.query_devices.return_value = devices
            mock_sd.query_hostapis.return_value = hostapis
            result = get_clean_mic_list()
        assert len(result) == 1
        assert result[0][1] == "Mic"

    def test_filters_junk_devices(self):
        devices = [
            _make_device("Stereo Mix (Realtek)", 2),
            _make_device("Real Mic", 1),
        ]
        hostapis = _make_hostapis("MME")
        with patch("select_mic.sd") as mock_sd:
            mock_sd.query_devices.return_value = devices
            mock_sd.query_hostapis.return_value = hostapis
            result = get_clean_mic_list()
        assert len(result) == 1
        assert result[0][1] == "Real Mic"

    def test_deduplicates_same_name_prefers_mme(self):
        """Same mic name under MME and WASAPI — should keep MME."""
        devices = [
            _make_device("Blue Yeti", 1, hostapi=0),  # MME
            _make_device("Blue Yeti", 1, hostapi=1),  # WASAPI
        ]
        hostapis = _make_hostapis("MME", "Windows WASAPI")
        with patch("select_mic.sd") as mock_sd:
            mock_sd.query_devices.return_value = devices
            mock_sd.query_hostapis.return_value = hostapis
            result = get_clean_mic_list()
        assert len(result) == 1
        assert result[0][2] == "MME"

    def test_deduplicates_prefers_directsound_over_wasapi(self):
        devices = [
            _make_device("Mic X", 1, hostapi=0),  # WASAPI
            _make_device("Mic X", 1, hostapi=1),  # DirectSound
        ]
        hostapis = _make_hostapis("Windows WASAPI", "Windows DirectSound")
        with patch("select_mic.sd") as mock_sd:
            mock_sd.query_devices.return_value = devices
            mock_sd.query_hostapis.return_value = hostapis
            result = get_clean_mic_list()
        assert len(result) == 1
        assert result[0][2] == "Windows DirectSound"

    def test_mme_truncation_dedup(self):
        """MME truncates names to 31 chars. Longer WASAPI names that start
        with the same prefix should be deduplicated."""
        mme_name = "Microphone (Realtek HD Audio)"  # 30 chars — fits MME
        wasapi_name = "Microphone (Realtek HD Audio) Extra Info"
        devices = [
            _make_device(mme_name, 1, hostapi=0),
            _make_device(wasapi_name, 1, hostapi=1),
        ]
        hostapis = _make_hostapis("MME", "Windows WASAPI")
        with patch("select_mic.sd") as mock_sd:
            mock_sd.query_devices.return_value = devices
            mock_sd.query_hostapis.return_value = hostapis
            result = get_clean_mic_list()
        # The WASAPI longer name should be deduped away
        names = [r[1] for r in result]
        assert mme_name in names
        assert wasapi_name not in names

    def test_returns_sorted_by_device_id(self):
        devices = [
            _make_device("Mic B", 1),
            _make_device("Mic A", 1),
            _make_device("Mic C", 1),
        ]
        hostapis = _make_hostapis("MME")
        with patch("select_mic.sd") as mock_sd:
            mock_sd.query_devices.return_value = devices
            mock_sd.query_hostapis.return_value = hostapis
            result = get_clean_mic_list()
        ids = [r[0] for r in result]
        assert ids == sorted(ids)

    def test_empty_device_list(self):
        with patch("select_mic.sd") as mock_sd:
            mock_sd.query_devices.return_value = []
            mock_sd.query_hostapis.return_value = []
            result = get_clean_mic_list()
        assert result == []

    def test_result_tuple_shape(self):
        devices = [_make_device("Test Mic", 2)]
        hostapis = _make_hostapis("MME")
        with patch("select_mic.sd") as mock_sd:
            mock_sd.query_devices.return_value = devices
            mock_sd.query_hostapis.return_value = hostapis
            result = get_clean_mic_list()
        assert len(result) == 1
        device_id, name, api = result[0]
        assert isinstance(device_id, int)
        assert isinstance(name, str)
        assert isinstance(api, str)
