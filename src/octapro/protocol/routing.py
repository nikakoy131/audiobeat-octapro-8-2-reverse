"""Routing matrix parser (30 signed int8 bytes, /10.0 dB; 0x80 = mute/-inf).

The device read-format packs the crosspoint row as 30 signed-int8 bytes
(NOT the 32 an earlier note assumed — bytes [30:34] of the block are the
per-channel gain float32, verified 2026-07-06). Reading 32 here would drag
the first two gain-float bytes in as bogus routing levels.
"""

from dataclasses import dataclass

ROUTING_LEN = 30


@dataclass
class RoutingMatrix:
    raw: bytes
    values: list[float]  # -inf where muted, else dB (e.g. 10.0 = 100%, -inf = off)


def parse_routing(data: bytes, offset: int = 0, length: int = ROUTING_LEN) -> RoutingMatrix:
    raw = bytes(data[offset : offset + length])
    values: list[float] = []
    for b in raw:
        if b == 0x80:
            values.append(float("-inf"))
        else:
            signed = b if b < 128 else b - 256
            values.append(signed / 10.0)
    return RoutingMatrix(raw=raw, values=values)
