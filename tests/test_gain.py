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


class TestEqBar:
    """_eq_bar must render fixed-width (25 visible chars) for table alignment."""

    def _visible(self, t) -> str:
        return t.plain

    def test_flat_center_line_only(self):
        from octapro.commands.read import _eq_bar

        v = self._visible(_eq_bar(0.0))
        assert len(v) == 25 and v[12] == "│"

    def test_full_boost_and_cut(self):
        from octapro.commands.read import _eq_bar

        boost = self._visible(_eq_bar(12.8))
        cut = self._visible(_eq_bar(-12.8))
        assert boost[13:25] == "█" * 12 and len(boost) == 25
        assert cut[0:12] == "█" * 12 and len(cut) == 25

    def test_mute(self):
        from octapro.commands.read import _eq_bar

        v = self._visible(_eq_bar(None))
        assert len(v) == 25 and v[12] == "✕"


class TestDbToKnob:
    def test_anchors_exact(self):
        from octapro.protocol.volume import KNOB_CALIBRATION, db_to_knob

        for step, db in KNOB_CALIBRATION:
            got, exact = db_to_knob(db)
            assert got == step and exact, f"anchor {step} -> {got}, exact={exact}"

    def test_interpolated_between_anchors(self):
        from octapro.protocol.volume import db_to_knob

        # +3.1 dB sits between knob 30 (+1.12) and knob 34 (+5.11)
        step, exact = db_to_knob(3.1)
        assert step == 32 and not exact

    def test_clamped_outside_range(self):
        from octapro.protocol.volume import db_to_knob

        assert db_to_knob(-99.0) == (0, False)
        assert db_to_knob(10.0) == (35, False)
