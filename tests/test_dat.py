import pytest

from octapro.protocol.constants import LPF_BYPASS_HZ
from octapro.protocol.dat import parse_dat


class TestParseDat:
    def test_returns_10_channels(self, dat_path):
        preset = parse_dat(dat_path)
        assert len(preset.channels) == 10

    def test_channel_indices_1_to_10(self, dat_path):
        preset = parse_dat(dat_path)
        assert [c.index for c in preset.channels] == list(range(1, 11))

    def test_ch7_lpf_near_80hz(self, dat_path):
        """CH7 is the sub-woofer left, LPF=80 Hz per CONTEXT_USER.md."""
        preset = parse_dat(dat_path)
        ch7 = preset.channels[6]
        assert abs(ch7.lpf_freq_hz - 80.0) < 10.0, f"Expected ~80 Hz, got {ch7.lpf_freq_hz}"

    def test_ch5_lpf_near_3500hz(self, dat_path):
        """CH5 is tweeter left, LPF=3500 Hz."""
        preset = parse_dat(dat_path)
        ch5 = preset.channels[4]
        assert abs(ch5.lpf_freq_hz - 3500.0) < 200.0, f"Expected ~3500 Hz, got {ch5.lpf_freq_hz}"

    def test_ch1_lpf_bypass(self, dat_path):
        """CH1 is front left, LPF=bypass (~20600 Hz)."""
        preset = parse_dat(dat_path)
        ch1 = preset.channels[0]
        assert abs(ch1.lpf_freq_hz - LPF_BYPASS_HZ) < 500.0, (
            f"Expected ~{LPF_BYPASS_HZ} Hz (bypass), got {ch1.lpf_freq_hz}"
        )

    def test_eq_bands_present(self, dat_path):
        preset = parse_dat(dat_path)
        for ch in preset.channels:
            assert len(ch.eq_bands) == 31

    def test_routing_matrix_parsed(self, dat_path):
        preset = parse_dat(dat_path)
        for ch in preset.channels:
            assert len(ch.routing.values) == 32

    def test_invalid_file(self, tmp_path):
        from octapro.errors import ParseError

        bad = tmp_path / "bad.dat"
        bad.write_bytes(b"XXXXX" + b"\x00" * 2380)
        with pytest.raises(ParseError):
            parse_dat(bad)
