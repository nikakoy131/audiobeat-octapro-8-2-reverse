"""Routing matrix parser (32 signed int8 bytes, /10.0 dB; 0x80 = mute/-inf)."""

from dataclasses import dataclass


@dataclass
class RoutingMatrix:
    raw: bytes
    values: list[float]  # -inf where muted, else dB (e.g. 10.0 = 100%, -inf = off)


def parse_routing(data: bytes, offset: int = 0) -> RoutingMatrix:
    raw = bytes(data[offset : offset + 32])
    values: list[float] = []
    for b in raw:
        if b == 0x80:
            values.append(float("-inf"))
        else:
            signed = b if b < 128 else b - 256
            values.append(signed / 10.0)
    return RoutingMatrix(raw=raw, values=values)
