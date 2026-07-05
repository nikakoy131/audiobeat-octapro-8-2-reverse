"""knob-vol mapping: remote knob step (0-35) ↔ dB.

Terminology: knob-vol = the remote panel knob; the software "Main" fader
is the *master* (CH0) and is a separate control — see PROTOCOL.md.

The firmware uses an audio-taper lookup table, not a formula. Anchors below
were live-calibrated 2026-07-04 by stepping the physical remote knob and
reading the float32 echoed in the keepalive response (PROTOCOL.md,
"Main volume readback"). Between anchors the step is linearly interpolated —
exact only at the anchors until more positions are sampled.
"""

KNOB_MIN = 0
KNOB_MAX = 35

# (knob step, dB) — live-verified anchor points
KNOB_CALIBRATION: list[tuple[int, float]] = [
    (0, -60.00),
    (5, -33.17),
    (15, -14.19),
    (25, -3.33),
    (30, 1.12),
    (34, 5.11),
    (35, 6.00),
]

_EPS = 0.005


def db_to_knob(db: float) -> tuple[int, bool]:
    """Map a main-volume dB value to the remote knob step (0-35).

    Returns (step, exact): exact=True when db matches a calibration anchor,
    False when the step is interpolated between anchors.
    """
    if db <= KNOB_CALIBRATION[0][1]:
        return KNOB_MIN, abs(db - KNOB_CALIBRATION[0][1]) < _EPS
    if db >= KNOB_CALIBRATION[-1][1]:
        return KNOB_MAX, abs(db - KNOB_CALIBRATION[-1][1]) < _EPS
    for (step_lo, db_lo), (step_hi, db_hi) in zip(
        KNOB_CALIBRATION, KNOB_CALIBRATION[1:], strict=False
    ):
        if abs(db - db_lo) < _EPS:
            return step_lo, True
        if db_lo < db < db_hi:
            frac = (db - db_lo) / (db_hi - db_lo)
            return round(step_lo + frac * (step_hi - step_lo)), False
    return KNOB_MAX, True  # db == last anchor (handled above, kept for safety)
