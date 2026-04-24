import struct

import pytest

from octapro.protocol.eq import EQ_BAND_COUNT, parse_eq_block


def _make_block(bands: list[tuple[float, int, int]] | None = None) -> bytes:
    if bands is None:
        bands = [(1000.0, 0x78, 0x0A)] * EQ_BAND_COUNT
    data = bytearray()
    for freq, gain, q in bands:
        data += struct.pack("<f", freq)
        data += bytes([gain, q])
    return bytes(data)


class TestParseEqBlock:
    def test_band_count(self):
        block = _make_block()
        bands = parse_eq_block(block)
        assert len(bands) == EQ_BAND_COUNT

    def test_flat_bands(self):
        block = _make_block()
        bands = parse_eq_block(block)
        for b in bands:
            assert b.gain_db == pytest.approx(0.0)
            assert b.q_byte == 0x0A

    def test_gain_decoded(self):
        first = (500.0, 0x82, 0x0A)  # 0x82 = 0x78 + 10 → +1.0 dB
        rest = [(1000.0, 0x78, 0x0A)] * (EQ_BAND_COUNT - 1)
        block = _make_block([first] + rest)
        bands = parse_eq_block(block)
        assert bands[0].freq_hz == pytest.approx(500.0, abs=0.1)
        assert bands[0].gain_db == pytest.approx(1.0, abs=0.1)

    def test_zero_indexed(self):
        block = _make_block()
        bands = parse_eq_block(block)
        assert bands[0].index == 0
        assert bands[-1].index == EQ_BAND_COUNT - 1

    def test_short_block_truncates(self):
        # Fewer than 31 bands — should not crash, just return fewer
        block = _make_block([(1000.0, 0x78, 0x0A)] * 5)
        bands = parse_eq_block(block)
        assert len(bands) == 5

    def test_warn_called_for_nondefault_q(self):
        warned: list[tuple] = []
        first = (500.0, 0x78, 0x2B)  # non-default Q
        rest = [(1000.0, 0x78, 0x0A)] * (EQ_BAND_COUNT - 1)
        block = _make_block([first] + rest)
        parse_eq_block(block, warn=lambda k, v, c: warned.append((k, v, c)))
        assert len(warned) == 1
        assert warned[0][0] == "eq_q_byte"
