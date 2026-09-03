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

    def test_no_warn_for_nondefault_but_plausible_q(self):
        # Q = byte/10 is verified; a user-set Q (1.5, 2.0, 4.3, 20.0) is data,
        # not an unknown — must not spam the research log on every read.
        warned: list[tuple] = []
        bands = [(500.0, 0x78, q) for q in (0x0F, 0x14, 0x2B, 0xC8, 0x04)]
        rest = [(1000.0, 0x78, 0x0A)] * (EQ_BAND_COUNT - len(bands))
        parse_eq_block(_make_block(bands + rest), warn=lambda k, v, c: warned.append((k, v, c)))
        assert warned == []

    def test_warn_called_for_implausible_q(self):
        warned: list[tuple] = []
        bands = [(500.0, 0x78, 0x00), (630.0, 0x78, 0xFF)]  # Q 0.0 and 25.5
        rest = [(1000.0, 0x78, 0x0A)] * (EQ_BAND_COUNT - len(bands))
        parse_eq_block(_make_block(bands + rest), warn=lambda k, v, c: warned.append((k, v, c)))
        assert [w[0] for w in warned] == ["eq_q_byte", "eq_q_byte"]
        assert [w[1] for w in warned] == ["0x00", "0xff"]


def test_eq_band_0x80_is_plus_0p8_not_mute():
    """0x80 is the channel-gain mute sentinel, but an ordinary +0.8 dB EQ band.

    Regression: the live CH1/CH2 tweeter curve reads 8k=0x81 (+0.9),
    10k=0x80, 12.5k=0x89 (+1.7). Decoding 0x80 as mute turned a smooth HF
    shelf into an impossible infinite notch on both channels.
    """
    import struct

    from octapro.protocol.eq import parse_eq_block

    raw = b"".join(
        struct.pack("<f", f) + bytes([g, 0x0A])
        for f, g in [(8000.0, 0x81), (10000.0, 0x80), (12500.0, 0x89)]
    )
    bands = parse_eq_block(raw)
    assert [round(b.gain_db, 1) for b in bands[:3]] == [0.9, 0.8, 1.7]


def test_eq_gain_roundtrips_through_0x80():
    """+0.8 dB must survive encode -> decode; it previously became MUTE/None."""
    from octapro.protocol.gain import db_to_byte, eq_byte_to_db

    assert db_to_byte(0.8) == 0x80
    assert eq_byte_to_db(db_to_byte(0.8)) == 0.8
