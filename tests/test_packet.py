import struct

import pytest

from octapro.protocol.constants import WRITE_DSP_TRAILER
from octapro.protocol.packet import (
    build_dsp_commit,
    build_read_channel,
    build_write_dsp,
    channel_addr,
    compute_checksum,
)


class TestChannelAddr:
    def test_ch1(self):
        assert channel_addr(1) == 0x01B7

    def test_ch7(self):
        assert channel_addr(7) == 0x07B7

    def test_ch10(self):
        assert channel_addr(10) == 0x0AB7

    def test_master_ch0(self):
        # ch0 = master volume — live-verified 2026-07-04
        assert channel_addr(0) == 0x00B7

    def test_invalid(self):
        with pytest.raises(ValueError):
            channel_addr(-1)
        with pytest.raises(ValueError):
            channel_addr(11)


class TestChecksum:
    def test_formula(self):
        pkt = bytearray(256)
        struct.pack_into("<H", pkt, 4, 0x07B7)   # addr CH7
        pkt[6] = 0x05                              # sub HPF_FREQ
        struct.pack_into("<f", pkt, 7, 80.0)       # 80 Hz
        pkt[11] = 0x05                             # slope
        pkt[12] = 0x00                             # type HPF
        csum = compute_checksum(pkt)
        assert 0 <= csum <= 0xFF

    def test_zero_packet(self):
        pkt = bytearray(256)
        assert compute_checksum(pkt) == (0 - 0x20) & 0xFF


class TestBuildReadChannel:
    def test_structure(self):
        pkt = build_read_channel(7)
        assert len(pkt) == 256
        assert pkt[0] == 0xE0
        assert pkt[1] == 0xA2
        assert pkt[2] == 0x05
        assert pkt[3] == 0x00

    def test_wire_bytes_match_capture(self):
        # usb1.pcapng frame 119: sub bytes are 04 <ch>, not <ch> 04 —
        # the checksum is a byte sum and cannot catch a swap here
        assert bytes(build_read_channel(1))[:9] == bytes.fromhex("e0a20500b000040195")
        assert bytes(build_read_channel(10))[:9] == bytes.fromhex("e0a20500b000040a9e")

    def test_magic_checksum(self):
        # Checksum is the observed magic 0x94+ch from captures
        pkt = build_read_channel(7)
        assert pkt[8] == 0x94 + 7

    def test_master(self):
        pkt = build_read_channel(0)
        assert pkt[8] == 0x94 + 0


class TestMasterVolumeWrite:
    """Wire bytes live-verified 2026-07-04: master volume = gain write to CH0."""

    def test_ch0_gain_write_bytes(self):
        from octapro.protocol.packet import build_write_dsp, channel_addr

        pkt = build_write_dsp(channel_addr(0), 0x26, 20000.0, 0x3C, 0x0A)
        # sent live; device ACKed ee bb and staged the volume change
        assert bytes(pkt[:16]) == bytes.fromhex("e0a20a00b7002600409c463c0a250010")

    def test_ch0_commit_bytes(self):
        from octapro.protocol.packet import build_dsp_commit

        pkt = build_dsp_commit(0)
        # sent live; commit applied the staged value to the master block
        assert bytes(pkt[:9]) == bytes.fromhex("e0a20500b700010098")

    def test_channel_addr_master(self):
        from octapro.protocol.packet import channel_addr

        assert channel_addr(0) == 0x00B7

    def test_channel_addr_rejects_out_of_range(self):
        import pytest

        from octapro.protocol.packet import channel_addr

        with pytest.raises(ValueError):
            channel_addr(11)
        with pytest.raises(ValueError):
            channel_addr(-1)


class TestParseKeepaliveKnobVol:
    """Live-captured keepalive responses at known remote-knob positions."""

    def _resp(self, float_hex: str, trailer: int) -> bytes:
        head = bytes.fromhex("0f00e0a20b00b00015000102")
        return head + bytes.fromhex(float_hex) + bytes([trailer]) + bytes(256 - 17)

    def test_knob_35_max(self):
        from octapro.protocol.packet import parse_keepalive_knob_vol

        vol, ok = parse_keepalive_knob_vol(self._resp("0000c040", 0xA8))
        assert vol == 6.0 and ok

    def test_knob_0_min(self):
        from octapro.protocol.packet import parse_keepalive_knob_vol

        vol, ok = parse_keepalive_knob_vol(self._resp("000070c2", 0xDA))
        assert vol == -60.0 and ok

    def test_knob_34(self):
        from octapro.protocol.packet import parse_keepalive_knob_vol

        vol, ok = parse_keepalive_knob_vol(self._resp("1f85a340", 0x2F))
        assert abs(vol - 5.11) < 0.001 and ok

    def test_bad_trailer_flagged(self):
        from octapro.protocol.packet import parse_keepalive_knob_vol

        vol, ok = parse_keepalive_knob_vol(self._resp("0000c040", 0x00))
        assert vol == 6.0 and not ok


class TestBuildSessionOpen:
    def test_wire_bytes_match_capture(self):
        # usb1.pcapng frame 107 — first packet the vendor app sends
        from octapro.protocol.packet import build_session_open

        assert bytes(build_session_open())[:9] == bytes.fromhex("e0a20500b7000311ab")


class TestBuildWriteDsp:
    def test_structure(self):
        pkt = build_write_dsp(0x07B7, 0x05, 80.0, 0x05, 0x00)
        assert pkt[0] == 0xE0
        assert pkt[2] == 0x0A

    def test_trailer(self):
        pkt = build_write_dsp(0x07B7, 0x05, 80.0, 0x05, 0x00)
        assert pkt[14:16] == WRITE_DSP_TRAILER

    def test_checksum_at_13(self):
        pkt = build_write_dsp(0x07B7, 0x05, 80.0, 0x05, 0x00)
        # Checksum stored at [13], not [8]
        assert pkt[8] == 0x00  # csum position for 0x0a is NOT [8]
        assert pkt[13] == compute_checksum(pkt)

    def test_float_written(self):
        pkt = build_write_dsp(0x07B7, 0x05, 123.456, 0x05, 0x00)
        recovered = struct.unpack_from("<f", pkt, 7)[0]
        assert abs(recovered - 123.456) < 0.001


class TestBuildDspCommit:
    def test_structure(self):
        pkt = build_dsp_commit(7)
        assert pkt[2] == 0x05  # CMD READ_BLOCK re-used as commit trigger
        addr = struct.unpack_from("<H", pkt, 4)[0]
        assert addr == channel_addr(7)
