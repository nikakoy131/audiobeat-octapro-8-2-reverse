import struct

from octapro.protocol.channel import BLOCK_LEN, parse_channel_block


def _build_block(
    hpf_hz: float = 80.0,
    hpf_slope: int = 0x05,
    lpf_hz: float = 3500.0,
    lpf_slope: int = 0x03,
) -> bytes:
    data = bytearray(BLOCK_LEN)
    data[0] = 0x00  # prefix
    # routing [1:33] — zeros (all muted)
    struct.pack_into("<f", data, 39, hpf_hz)
    data[43] = hpf_slope
    struct.pack_into("<f", data, 45, lpf_hz)
    data[49] = lpf_slope
    data[52] = 0x06  # EQ marker
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
        assert len(block.routing.values) == 32

    def test_unknown_bytes_recorded(self):
        raw = _build_block()
        block = parse_channel_block(raw, ch=1)
        assert "bytes_33_39" in block.unknown_bytes


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
