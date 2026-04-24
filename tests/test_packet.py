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

    def test_invalid(self):
        with pytest.raises(ValueError):
            channel_addr(0)
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

    def test_magic_checksum(self):
        # Checksum is the observed magic 0x94+ch from captures
        pkt = build_read_channel(7)
        assert pkt[8] == 0x94 + 7

    def test_master(self):
        pkt = build_read_channel(0)
        assert pkt[8] == 0x94 + 0


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
