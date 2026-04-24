import pytest

from octapro.protocol.gain import byte_to_db, db_to_byte, format_gain


class TestByteToDb:
    def test_mute(self):
        assert byte_to_db(0x80) is None

    def test_zero_db(self):
        assert byte_to_db(0x78) == pytest.approx(0.0)

    def test_plus_10(self):
        assert byte_to_db(0xDC) == pytest.approx(10.0)

    def test_minus_1(self):
        assert byte_to_db(0x6E) == pytest.approx(-1.0)

    def test_minus_3(self):
        assert byte_to_db(0x5A) == pytest.approx(-3.0)


class TestDbToByte:
    def test_zero(self):
        assert db_to_byte(0.0) == 0x78

    def test_clamp_high(self):
        result = db_to_byte(9999.0)
        assert result == 0xFF

    def test_clamp_low(self):
        result = db_to_byte(-9999.0)
        assert result == 0


class TestRoundtrip:
    @pytest.mark.parametrize("db", [-12.0, -6.0, -3.0, -1.0, 0.0, 1.0, 3.0, 6.0, 10.0])
    def test_roundtrip(self, db):
        b = db_to_byte(db)
        recovered = byte_to_db(b)
        assert recovered is not None
        assert abs(recovered - db) < 0.15  # 0.1 dB step, small tolerance


class TestFormatGain:
    def test_mute(self):
        assert format_gain(0x80) == "MUTE"

    def test_zero(self):
        assert format_gain(0x78) == "+0.0 dB"

    def test_positive(self):
        s = format_gain(0xDC)
        assert s.startswith("+") and "10.0" in s
