import struct

from octapro.protocol.channel import (
    BLOCK_LEN,
    BLOCK_WIRE_LEN,
    PHASE_INVERT_OFFSET,
    parse_channel_block,
)


def _build_block(
    hpf_hz: float = 80.0,
    hpf_slope: int = 0x05,
    lpf_hz: float = 3500.0,
    lpf_slope: int = 0x03,
    gain_db: float = -6.0,
    delay_ms: float = 1.5,
    speaker_type: int = 0x06,
    muted: bool = False,
    phase_inverted: bool = False,
) -> bytes:
    data = bytearray(BLOCK_LEN)
    data[0] = 0x00  # prefix
    # routing [1:31] — zeros (no inputs routed); byte 29 doubles as the mute
    # flag, byte 30 (last byte of this range) doubles as the phase-invert flag
    data[29] = 1 if muted else 0
    data[30] = 1 if phase_inverted else 0
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

    def test_no_warn_for_wire_length_block(self):
        # BLE delivers exactly the 240 bytes the device sends (no USB transfer
        # padding) — that is a complete block, not a short one.
        warned: list[tuple] = []
        raw = _build_block(gain_db=-3.0, delay_ms=1.0)[:BLOCK_WIRE_LEN]
        block = parse_channel_block(raw, ch=1, warn=lambda k, v, c: warned.append((k, v, c)))
        assert [w[0] for w in warned] == []
        assert block.gain_db == -3.0
        assert block.delay_ms == 1.0
        assert len(block.eq_bands) == 31

    def test_warn_on_truncated_block(self):
        warned: list[tuple] = []
        raw = _build_block()[: BLOCK_WIRE_LEN - 1]
        parse_channel_block(raw, ch=1, warn=lambda k, v, c: warned.append((k, v, c)))
        assert ("short_block", BLOCK_WIRE_LEN - 1, f"ch=1 expected {BLOCK_WIRE_LEN}") in warned

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

    def test_phase_invert_flag_set(self):
        raw = _build_block(phase_inverted=True)
        block = parse_channel_block(raw, ch=1)
        assert block.phase_inverted is True

    def test_phase_invert_flag_clear(self):
        raw = _build_block(phase_inverted=False)
        block = parse_channel_block(raw, ch=1)
        assert block.phase_inverted is False


class TestChannelPhaseInvertLive:
    """Live-captured 2026-08-24 (subwoofer channels, M3 preset): raw READ_BLOCK
    payloads taken immediately before/after `write phase --invert` / `--normal`
    with no other write in between. On both CH7 and CH8 exactly two bytes move:
    [30] (0x00 <-> 0x01) and the [239] checksum-like trailer — the same pattern
    already established for the mute flag at [29] and for the master-block
    preset slot at [7].

    Over USB the device answers with 248 bytes (240 real + GET_REPORT
    padding); these fixtures are trimmed to BLOCK_LEN (242) — the extra
    bytes are zero padding. Note the trailer is also
    channel-dependent (CH7 normal 0xd1, CH8 normal 0xd2) even though the two
    channels' blocks are otherwise byte-identical here, so [239] is not a pure
    function of the block contents.
    """

    CH7_INVERTED = bytes.fromhex(
        "00b2b2808080800000b2b2808080800000b2b2b2b2b2b23232b2b23232000100"
        "000000000000000000b04105000000a042030001030000a041780a0000c84178"
        "0a0000fc41780a00002042a00f00004842780a00007c42780a0000a042780a00"
        "00c842780a0000fa42780a00002043780a00004843780a00007a43780a00809d"
        "43780a0000c843780a0000fa43780a00801d44780a00004844780a00007a4478"
        "0a00409c44780a0000c844780a0000fa44780a00401c45780a00e04445780a00"
        "007a45780a00409c45780a00e0c445780a0000fa45780a00401c46780a005043"
        "46780a00007a46780a00409c46780ad20000"
    )
    CH7_NORMAL = bytes.fromhex(
        "00b2b2808080800000b2b2808080800000b2b2b2b2b2b23232b2b23232000000"
        "000000000000000000b04105000000a042030001030000a041780a0000c84178"
        "0a0000fc41780a00002042a00f00004842780a00007c42780a0000a042780a00"
        "00c842780a0000fa42780a00002043780a00004843780a00007a43780a00809d"
        "43780a0000c843780a0000fa43780a00801d44780a00004844780a00007a4478"
        "0a00409c44780a0000c844780a0000fa44780a00401c45780a00e04445780a00"
        "007a45780a00409c45780a00e0c445780a0000fa45780a00401c46780a005043"
        "46780a00007a46780a00409c46780ad10000"
    )
    CH8_INVERTED = bytes.fromhex(
        "00b2b2808080800000b2b2808080800000b2b2b2b2b2b23232b2b23232000100"
        "000000000000000000b04105000000a042030001030000a041780a0000c84178"
        "0a0000fc41780a00002042a00f00004842780a00007c42780a0000a042780a00"
        "00c842780a0000fa42780a00002043780a00004843780a00007a43780a00809d"
        "43780a0000c843780a0000fa43780a00801d44780a00004844780a00007a4478"
        "0a00409c44780a0000c844780a0000fa44780a00401c45780a00e04445780a00"
        "007a45780a00409c45780a00e0c445780a0000fa45780a00401c46780a005043"
        "46780a00007a46780a00409c46780ad30000"
    )
    CH8_NORMAL = bytes.fromhex(
        "00b2b2808080800000b2b2808080800000b2b2b2b2b2b23232b2b23232000000"
        "000000000000000000b04105000000a042030001030000a041780a0000c84178"
        "0a0000fc41780a00002042a00f00004842780a00007c42780a0000a042780a00"
        "00c842780a0000fa42780a00002043780a00004843780a00007a43780a00809d"
        "43780a0000c843780a0000fa43780a00801d44780a00004844780a00007a4478"
        "0a00409c44780a0000c844780a0000fa44780a00401c45780a00e04445780a00"
        "007a45780a00409c45780a00e0c445780a0000fa45780a00401c46780a005043"
        "46780a00007a46780a00409c46780ad20000"
    )

    def test_fixture_lengths(self):
        for raw in (self.CH7_INVERTED, self.CH7_NORMAL, self.CH8_INVERTED, self.CH8_NORMAL):
            assert len(raw) == BLOCK_LEN

    def test_ch7_only_flag_and_trailer_differ(self):
        diffs = [i for i in range(BLOCK_LEN) if self.CH7_INVERTED[i] != self.CH7_NORMAL[i]]
        assert diffs == [PHASE_INVERT_OFFSET, 239]

    def test_ch8_only_flag_and_trailer_differ(self):
        diffs = [i for i in range(BLOCK_LEN) if self.CH8_INVERTED[i] != self.CH8_NORMAL[i]]
        assert diffs == [PHASE_INVERT_OFFSET, 239]

    def test_inverted_decodes_true(self):
        assert parse_channel_block(self.CH7_INVERTED, ch=7).phase_inverted is True
        assert parse_channel_block(self.CH8_INVERTED, ch=8).phase_inverted is True

    def test_normal_decodes_false(self):
        assert parse_channel_block(self.CH7_NORMAL, ch=7).phase_inverted is False
        assert parse_channel_block(self.CH8_NORMAL, ch=8).phase_inverted is False

    def test_phase_flag_does_not_disturb_the_rest_of_the_decode(self):
        inv = parse_channel_block(self.CH7_INVERTED, ch=7)
        norm = parse_channel_block(self.CH7_NORMAL, ch=7)
        # 80 Hz / 24 dB LR high-pass, the M3 sub tune — unchanged by the flag
        assert abs(inv.hpf_freq_hz - norm.hpf_freq_hz) < 0.01
        assert inv.gain_db == norm.gain_db
        assert inv.delay_ms == norm.delay_ms
        assert inv.muted is False and norm.muted is False


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
