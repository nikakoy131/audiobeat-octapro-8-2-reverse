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
