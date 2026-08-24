import struct

from octapro.protocol.channel import BLOCK_LEN, parse_channel_block


def _build_block(
    hpf_hz: float = 80.0,
    hpf_slope: int = 0x05,
    lpf_hz: float = 3500.0,
    lpf_slope: int = 0x03,
    gain_db: float = -6.0,
    delay_ms: float = 1.5,
    speaker_type: int = 0x06,
    muted: bool = False,
) -> bytes:
    data = bytearray(BLOCK_LEN)
    data[0] = 0x00  # prefix
    # routing [1:31] — zeros (no inputs routed); byte 29 doubles as the mute flag
    data[29] = 1 if muted else 0
    struct.pack_into("<f", data, 31, gain_db)
    struct.pack_into("<f", data, 35, delay_ms)
    struct.pack_into("<f", data, 39, hpf_hz)
    data[43] = hpf_slope
    struct.pack_into("<f", data, 45, lpf_hz)
    data[49] = lpf_slope
    data[52] = speaker_type
    for i in range(31):
        off = 53 + i * 6
        struct.pack_into("<f", data, off, 1000.0)
        data[off + 4] = 0x78  # 0 dB
        data[off + 5] = 0x0A  # default Q
    return bytes(data)


class TestParseChannelBlock:
    def test_hpf_freq(self):
        raw = _build_block(hpf_hz=80.0)
        block = parse_channel_block(raw, ch=7)
        assert abs(block.hpf_freq_hz - 80.0) < 0.1

    def test_hpf_slope(self):
        raw = _build_block(hpf_slope=0x05)
        block = parse_channel_block(raw, ch=7)
        assert block.hpf_slope_byte == 0x05

    def test_lpf_freq(self):
        raw = _build_block(lpf_hz=3500.0)
        block = parse_channel_block(raw, ch=5)
        assert abs(block.lpf_freq_hz - 3500.0) < 0.1

    def test_lpf_slope(self):
        raw = _build_block(lpf_slope=0x03)
        block = parse_channel_block(raw, ch=5)
        assert block.lpf_slope_byte == 0x03

    def test_eq_band_count(self):
        raw = _build_block()
        block = parse_channel_block(raw, ch=1)
        assert len(block.eq_bands) == 31

    def test_flat_eq(self):
        raw = _build_block()
        block = parse_channel_block(raw, ch=1)
        active = [b for b in block.eq_bands if b.gain_db is not None and abs(b.gain_db) > 0.05]
        assert len(active) == 0

    def test_warn_on_unknown_slope(self):
        warned: list[tuple] = []
        raw = _build_block(hpf_slope=0xFF)
        parse_channel_block(raw, ch=1, warn=lambda k, v, c: warned.append((k, v, c)))
        kinds = [w[0] for w in warned]
        assert "hpf_slope_code" in kinds

    def test_routing_parsed(self):
        raw = _build_block()
        block = parse_channel_block(raw, ch=1)
        # routing is 30 bytes; [30:34] onward is the gain float32 — reading 32
        # here would misinterpret the low gain bytes as routing levels
        assert len(block.routing.values) == 30

    def test_routing_does_not_eat_gain(self):
        # a distinctive gain must NOT leak into the routing values
        raw = _build_block(gain_db=-10.0)
        block = parse_channel_block(raw, ch=1)
        assert block.gain_db == -10.0
        assert len(block.routing.values) == 30

    def test_unknown_bytes_recorded(self):
        raw = _build_block()
        block = parse_channel_block(raw, ch=1)
        assert "byte_51" in block.unknown_bytes

    def test_gain_delay_speaker_decoded(self):
        raw = _build_block(gain_db=-10.0, delay_ms=2.5, speaker_type=0x01)
        block = parse_channel_block(raw, ch=1)
        assert block.gain_db == -10.0
        assert block.delay_ms == 2.5
        assert block.speaker_type_byte == 0x01

    def test_muted_flag_set(self):
        raw = _build_block(muted=True)
        block = parse_channel_block(raw, ch=1)
        assert block.muted is True

    def test_muted_flag_clear(self):
        raw = _build_block(muted=False)
        block = parse_channel_block(raw, ch=1)
        assert block.muted is False


class TestParseMasterBlock:
    """Fixture = exact 137-byte master block dumped from the live device
    2026-07-04 (remote knob at 35 -> main volume +6.0 dB)."""

    LIVE_BLOCK = bytes.fromhex(
        "005555555555000201" "0000c040" "00000000000000000000000000000000"
        "b0c200"
        "0000010100010002000400080010002000400080000001000201000200000201"
        "01ffff030000010002000400080010002000400080000001000200000000"
        "27413233392d412d44503630332d55352e362d3235303131302d445350313435322d424d50383835"
        "8c0000"
    )

    def test_fixture_length(self):
        assert len(self.LIVE_BLOCK) == 137

    def test_volume(self):
        from octapro.protocol.channel import parse_master_block

        block = parse_master_block(self.LIVE_BLOCK)
        assert block.volume_db == 6.0

    def test_noise_gate(self):
        # float32 at [27:31] = -88.0 — matches the factory "Noise gate
        # threshold" dialog on manual p.9; identical in usb1.pcapng frame 162
        from octapro.protocol.channel import parse_master_block

        block = parse_master_block(self.LIVE_BLOCK)
        assert block.noise_gate_db == -88.0

    def test_firmware(self):
        from octapro.protocol.channel import parse_master_block

        block = parse_master_block(self.LIVE_BLOCK)
        assert block.firmware == "A239-A-DP603-U5.6-250110-DSP1452-BMP885"

    def test_preset_slot(self):
        # byte [7] = 0x02 in this fixture -> M2 was the active slot on 2026-07-04
        from octapro.protocol.channel import parse_master_block

        block = parse_master_block(self.LIVE_BLOCK)
        assert block.preset_slot == 2


class TestMasterBlockPresetSlotLive:
    """Live-captured 2026-08-24: raw `read master` before/after switching the RC
    from M2 to M1 with no other device command sent in between. The two captures
    differ only at offset [7] (0x02 -> 0x01) and the [134] checksum-like trailer
    (0xe6 -> 0xe5) — confirms [7] is the active preset slot, not a static prefix
    byte as previously catalogued."""

    M2_BLOCK = bytes.fromhex(
        "005555555555000201000098c100000000000000000000000000000000b0c2"
        "00000001010001000200040008001000200040008000000100020100020000"
        "030101ffff03000001000200040008001000200040008000000100020000000027"
        "413233392d412d44503630332d55352e362d3235303131302d445350313435322d"
        "424d50383835e60000"
    )[:137]

    M1_BLOCK = bytes.fromhex(
        "005555555555000101000098c100000000000000000000000000000000b0c2"
        "00000001010001000200040008001000200040008000000100020100020000"
        "030101ffff03000001000200040008001000200040008000000100020000000027"
        "413233392d412d44503630332d55352e362d3235303131302d445350313435322d"
        "424d50383835e50000"
    )[:137]

    def test_m2_capture(self):
        from octapro.protocol.channel import parse_master_block

        assert parse_master_block(self.M2_BLOCK).preset_slot == 2

    def test_m1_capture(self):
        from octapro.protocol.channel import parse_master_block

        assert parse_master_block(self.M1_BLOCK).preset_slot == 1

    def test_only_slot_and_trailer_differ(self):
        diffs = [
            i for i in range(137) if self.M2_BLOCK[i] != self.M1_BLOCK[i]
        ]
        assert diffs == [7, 134]
