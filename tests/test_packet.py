import struct

import pytest

from octapro.protocol.constants import WRITE_DSP_TRAILER
from octapro.protocol.packet import (
    build_bridge,
    build_dsp_commit,
    build_mute,
    build_phase,
    build_read_channel,
    build_write_dsp,
    build_write_master_volume,
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
    """CMD 0x0a WRITE_DSP builder regression test. NOTE: the 2026-07-04 claim
    that this writes master volume was RETRACTED — CH0 WRITE_DSP force-switches
    the input source. The real volume write is CMD 0x08 (see
    TestBuildChannelGain / build_write_master_volume). Kept only to pin the
    builder's byte layout."""

    def test_ch0_write_dsp_bytes(self):
        from octapro.protocol.packet import build_write_dsp, channel_addr

        pkt = build_write_dsp(channel_addr(0), 0x26, 20000.0, 0x3C, 0x0A)
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


class TestBuildWriteMasterVolume:
    """Live-captured 2026-07-05: CMD 0x08 SUB 0x0c direct master-volume write.

    Captured by replaying the vendor app's own traffic through a Linux uhid
    shim while dragging the Main fader (docs/LINUX_UHID_SHIM_PLAN.md). Each
    (dB, checksum) pair below is a distinct real packet the app sent; the
    last one is an independently-verified sample (dragged to "-20.0 dB" on
    the app's own UI, decoded here to -20.02 dB).
    """

    LIVE_SAMPLES = [
        (-35.25, 0x72),
        (-10.50, 0x8C),
        (-17.48, 0xD0),
        (-35.88, 0x18),
        (-0.98, 0x05),
        (-25.10, 0xC5),
        (-6.06, 0x94),
        (-6.69, 0xC8),
        (-13.04, 0x2E),
        (-16.21, 0xA7),
        (-19.38, 0x46),
        (-20.65, 0x6F),
        (-21.29, 0x4B),
        (-21.92, 0x98),
        (-20.02, 0x22),
    ]

    def test_structure(self):
        pkt = build_write_master_volume(-10.5)
        assert pkt[0:2] == bytes.fromhex("e0a2")
        assert pkt[2] == 0x08
        assert pkt[3] == 0x00
        assert pkt[4:6] == bytes.fromhex("b700")  # addr = channel_addr(0)
        assert pkt[6] == 0x0C

    def test_no_write_dsp_trailer(self):
        # unlike CMD 0x0a, there's no [14:16] trailer for this command
        pkt = build_write_master_volume(-10.5)
        assert pkt[12:16] == bytes(4)

    def test_live_samples_roundtrip_and_checksum(self):
        for db, expected_checksum in self.LIVE_SAMPLES:
            pkt = build_write_master_volume(db)
            recovered = struct.unpack_from("<f", pkt, 7)[0]
            assert abs(recovered - db) < 0.005
            assert pkt[11] == expected_checksum


class TestBuildChannelGain:
    """Live-captured 2026-07-06: CMD 0x08 sub 0x03 channel fader, from
    dragging CH3 to -6.0 dB. Same volume-write family as master volume."""

    def test_ch3_minus6_live_bytes(self):
        from octapro.protocol.packet import build_channel_gain

        assert bytes(build_channel_gain(3, -6.0))[:12] == bytes.fromhex("e0a20800b703030000c0c01d")

    def test_structure_and_sub_byte(self):
        from octapro.protocol.packet import build_channel_gain

        pkt = build_channel_gain(7, -3.0)
        assert pkt[2] == 0x08
        assert struct.unpack_from("<H", pkt, 4)[0] == channel_addr(7)
        assert pkt[6] == 0x03
        assert abs(struct.unpack_from("<f", pkt, 7)[0] - (-3.0)) < 0.001

    def test_ch0_rejected(self):
        import pytest

        from octapro.protocol.packet import build_channel_gain

        with pytest.raises(ValueError):
            build_channel_gain(0, -6.0)


class TestBuildEqBand:
    """Live-captured 2026-07-06: CMD 0x0a EQ band write (gain+freq+Q in one
    packet). sub-byte = 0x08 + (band-1); Q byte = round(Q*10)."""

    def test_band18_1khz_plus6_live_bytes(self):
        from octapro.protocol.packet import build_eq_band

        # ch1 band 18 (1 kHz) +6.0 dB, default Q 1.0
        pkt = build_eq_band(1, 18, gain_db=6.0)
        assert bytes(pkt[:16]) == bytes.fromhex("e0a20a00b7011900007a44b40a2d0000")

    def test_band8_100hz_minus5_live_bytes(self):
        from octapro.protocol.packet import build_eq_band

        pkt = build_eq_band(1, 8, gain_db=-5.0)
        assert bytes(pkt[:16]) == bytes.fromhex("e0a20a00b7010f0000c842460a010000")

    def test_band15_freq_q_live(self):
        import struct

        from octapro.protocol.packet import build_eq_band

        # ch3 band 15, 0.0 dB, Q 2.9; app's drag landed on this exact float
        pkt = build_eq_band(3, 15, gain_db=0.0, freq_hz=519.998779296875, q=2.9)
        assert bytes(pkt[:14]) == bytes.fromhex("e0a20a00b70316ecff0144781d75")
        # exact 520.0 via the builder differs only in the freq float
        pkt2 = build_eq_band(3, 15, gain_db=0.0, freq_hz=520.0, q=2.9)
        assert pkt2[6] == 0x16 and pkt2[11] == 0x78 and pkt2[12] == 0x1D
        assert abs(struct.unpack_from("<f", pkt2, 7)[0] - 520.0) < 0.001

    def test_sub_byte_encodes_band(self):
        from octapro.protocol.packet import build_eq_band

        assert build_eq_band(1, 1)[6] == 0x08
        assert build_eq_band(1, 8)[6] == 0x0F
        assert build_eq_band(1, 18)[6] == 0x19
        assert build_eq_band(1, 31)[6] == 0x26

    def test_q_encoding(self):
        from octapro.protocol.packet import build_eq_band

        assert build_eq_band(1, 18, q=1.0)[12] == 0x0A  # default
        assert build_eq_band(1, 18, q=2.9)[12] == 0x1D  # live-verified

    def test_band_out_of_range_rejected(self):
        import pytest

        from octapro.protocol.packet import build_eq_band

        with pytest.raises(ValueError):
            build_eq_band(1, 0)
        with pytest.raises(ValueError):
            build_eq_band(1, 32)


class TestBuildChannelDelay:
    """Live-captured 2026-07-06: CMD 0x08 sub 0x04 time-alignment delay, from
    dragging CH2's delay to 1.512 ms. float32 milliseconds directly."""

    def test_ch2_live_bytes(self):
        from octapro.protocol.packet import build_channel_delay

        expected = bytes.fromhex("e0a20800b702043789c13f5d")
        assert bytes(build_channel_delay(2, 1.512))[:12] == expected

    def test_structure_and_sub_byte(self):
        from octapro.protocol.packet import build_channel_delay

        pkt = build_channel_delay(4, 0.5)
        assert pkt[2] == 0x08
        assert struct.unpack_from("<H", pkt, 4)[0] == channel_addr(4)
        assert pkt[6] == 0x04
        assert abs(struct.unpack_from("<f", pkt, 7)[0] - 0.5) < 1e-6

    def test_ch0_rejected(self):
        import pytest

        from octapro.protocol.packet import build_channel_delay

        with pytest.raises(ValueError):
            build_channel_delay(0, 1.0)


class TestBuildMute:
    """Live-captured 2026-07-06 via the uhid shim: CMD 0x05 mute toggle.
    Master and per-channel use different sub-bytes (byte[6]) — both verified
    byte-perfect incl. checksum: master on/off, channels 2/6/10 mute, ch6
    unmute."""

    def test_master_mute_on_bytes(self):
        assert bytes(build_mute(0, True))[:9] == bytes.fromhex("e0a20500b7000d01a5")

    def test_master_mute_off_bytes(self):
        assert bytes(build_mute(0, False))[:9] == bytes.fromhex("e0a20500b7000d00a4")

    def test_master_only_state_and_checksum_differ(self):
        on = bytes(build_mute(0, True))
        off = bytes(build_mute(0, False))
        assert on[7] == 0x01 and off[7] == 0x00
        assert on[:7] == off[:7]
        assert on[9:] == off[9:]

    def test_channel_mute_on_live_samples(self):
        # exact wire bytes captured from the app muting CH2/6/10
        assert bytes(build_mute(2, True))[:9] == bytes.fromhex("e0a20500b70201019b")
        assert bytes(build_mute(6, True))[:9] == bytes.fromhex("e0a20500b70601019f")
        assert bytes(build_mute(10, True))[:9] == bytes.fromhex("e0a20500b70a0101a3")

    def test_channel_unmute_live_sample(self):
        # captured from the app unmuting CH6: byte[7] 01->00, checksum 9f->9e
        assert bytes(build_mute(6, False))[:9] == bytes.fromhex("e0a20500b70601009e")

    def test_channel_uses_sub_byte_01_not_0d(self):
        pkt = build_mute(7, True)
        assert struct.unpack_from("<H", pkt, 4)[0] == channel_addr(7)
        assert pkt[6] == 0x01  # per-channel sub-byte, NOT the master's 0x0d
        assert pkt[8] == compute_checksum(_zeroed_csum(pkt))


def _zeroed_csum(pkt: bytes) -> bytes:
    # helper: compute_checksum sums [4:13] incl. the checksum slot [8];
    # verify against a copy with [8] cleared so the round-trip is well-defined
    b = bytearray(pkt)
    b[8] = 0
    return bytes(b)


class TestBuildPhase:
    """Live-captured 2026-07-06 via the uhid shim: CMD 0x05 byte[6]=0x02
    phase invert, from toggling channel 6. Both samples byte-perfect."""

    def test_invert_live_sample(self):
        assert bytes(build_phase(6, True))[:9] == bytes.fromhex("e0a20500b7060201a0")

    def test_normal_live_sample(self):
        assert bytes(build_phase(6, False))[:9] == bytes.fromhex("e0a20500b70602009f")

    def test_selector_and_addr(self):
        pkt = build_phase(3, True)
        assert struct.unpack_from("<H", pkt, 4)[0] == channel_addr(3)
        assert pkt[6] == 0x02 and pkt[7] == 0x01
        assert pkt[8] == compute_checksum(_zeroed_csum(pkt))


class TestBuildEqPass:
    """Live-captured 2026-07-06 (ch7): CMD 0x05 channel-flag selector 0x07 =
    EQ pass/bypass."""

    def test_bypass_on_live_bytes(self):
        from octapro.protocol.packet import build_eq_pass

        assert bytes(build_eq_pass(7, True))[:9] == bytes.fromhex("e0a20500b7070701a6")

    def test_bypass_off_live_bytes(self):
        from octapro.protocol.packet import build_eq_pass

        assert bytes(build_eq_pass(7, False))[:9] == bytes.fromhex("e0a20500b7070700a5")


class TestBuildBridge:
    """Live-captured 2026-07-06: CMD 0x1c bridge CH7+CH8 (only bridgeable
    pair). Both states byte-perfect incl. the [4:31] checksum."""

    ON = bytes.fromhex("e0a21c00b70028010002000400080010002000c000800000010002000400084d")
    OFF = bytes.fromhex("e0a21c00b70028010002000400080010002000400080000001000200040008cd")

    def test_bridged_bytes(self):
        assert bytes(build_bridge(True))[:32] == self.ON

    def test_unbridged_bytes(self):
        assert bytes(build_bridge(False))[:32] == self.OFF

    def test_only_state_bit_and_checksum_differ(self):
        on = bytes(build_bridge(True))
        off = bytes(build_bridge(False))
        diffs = [i for i in range(256) if on[i] != off[i]]
        assert diffs == [19, 31]
        assert on[19] == 0xC0 and off[19] == 0x40


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


class TestParseKeepaliveSource:
    """Keepalive byte [11] = input source ID; live-mapped 2026-07-05 by
    cycling the remote panel's source menu."""

    def _resp(self, source_id: int, float_hex: str, trailer: int) -> bytes:
        head = bytes.fromhex("0f00e0a20b00b000150001") + bytes([source_id])
        return head + bytes.fromhex(float_hex) + bytes([trailer]) + bytes(256 - 17)

    def test_opt(self):
        from octapro.protocol.packet import parse_keepalive_source

        # live raw: 15 00 01 02 | 29 5c 8f 3f | fb  (opt, knob 30)
        assert parse_keepalive_source(self._resp(0x02, "295c8f3f", 0xFB)) == 0x02

    def test_low_level(self):
        from octapro.protocol.packet import parse_keepalive_source

        # live raw: 15 00 01 01 | 00 00 00 00 | a7  (low level, 0.0 dB)
        assert parse_keepalive_source(self._resp(0x01, "00000000", 0xA7)) == 0x01

    def test_usb_audio(self):
        from octapro.protocol.packet import parse_keepalive_source

        # live raw: 15 00 01 03 | 00 00 20 c1 | 8a  (USB AUDIO, -10.0 dB)
        assert parse_keepalive_source(self._resp(0x03, "000020c1", 0x8A)) == 0x03

    def test_live_trailers_validate(self):
        # the three live captures above must also pass the trailer checksum
        from octapro.protocol.packet import parse_keepalive_knob_vol

        for sid, fhex, trailer in [
            (0x02, "295c8f3f", 0xFB),
            (0x01, "00000000", 0xA7),
            (0x03, "000020c1", 0x8A),
        ]:
            _, ok = parse_keepalive_knob_vol(self._resp(sid, fhex, trailer))
            assert ok


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
