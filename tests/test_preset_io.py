"""Tests for .dat import/export (offline)."""

from pathlib import Path

from octapro.commands.preset_io import (
    channel_payload_to_dat_block,
    dat_channel_packets,
    serialize_dat,
)
from octapro.protocol.dat import BLOCK_LEN, parse_dat

DAT = Path(__file__).resolve().parent.parent / "dsp_m2_decoding.dat"


class TestSerializeRoundTrip:
    def test_serialize_matches_real_file(self):
        raw = DAT.read_bytes()
        blocks = [raw[5 + i * BLOCK_LEN : 5 + (i + 1) * BLOCK_LEN] for i in range(10)]
        assert serialize_dat(blocks) == raw  # header + blocks + 2-byte footer

    def test_serialize_rejects_wrong_count(self):
        import pytest

        with pytest.raises(ValueError):
            serialize_dat([b"\x00" * BLOCK_LEN] * 9)

    def test_payload_to_block_drops_prefix(self):
        payload = bytes([0x00]) + bytes(range(1, 1 + BLOCK_LEN)) + b"\xff\x00\x00"
        block = channel_payload_to_dat_block(payload)
        assert len(block) == BLOCK_LEN
        assert block == bytes(range(1, 1 + BLOCK_LEN))  # [1:239], prefix dropped


class TestImportPlan:
    def test_packets_cover_expected_params(self):
        preset = parse_dat(DAT)
        ch1 = next(c for c in preset.channels if c.index == 1)
        labels = [lbl for lbl, _ in dat_channel_packets(ch1)]
        assert any("gain" in lbl for lbl in labels)
        assert any("delay" in lbl for lbl in labels)
        assert any("speaker" in lbl for lbl in labels)
        assert any("HPF" in lbl for lbl in labels)
        assert any("LPF" in lbl for lbl in labels)
        assert sum("EQ band" in lbl for lbl in labels) == 31  # all bands by default

    def test_gain_packet_is_channel_gain(self):
        from octapro.protocol.packet import build_channel_gain

        preset = parse_dat(DAT)
        ch1 = next(c for c in preset.channels if c.index == 1)
        gain_pkt = next(pkt for lbl, pkt in dat_channel_packets(ch1) if "gain" in lbl)
        assert gain_pkt == bytes(build_channel_gain(1, ch1.gain_db))  # CH1 gain -10.0

    def test_skip_flat_eq_reduces_count(self):
        preset = parse_dat(DAT)
        ch2 = next(c for c in preset.channels if c.index == 2)
        full = dat_channel_packets(ch2, include_flat_eq=True)
        lean = dat_channel_packets(ch2, include_flat_eq=False)
        assert len(lean) <= len(full)
