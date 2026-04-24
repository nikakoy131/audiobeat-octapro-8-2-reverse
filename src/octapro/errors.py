class OctaProError(Exception):
    pass


class DeviceNotFound(OctaProError):
    pass


class ChecksumMismatch(OctaProError):
    def __init__(self, expected: int, got: int, context: str = "") -> None:
        self.expected = expected
        self.got = got
        detail = f" ({context})" if context else ""
        super().__init__(
            f"checksum mismatch: expected 0x{expected:02x}, got 0x{got:02x}{detail}"
        )


class UnknownStatus(OctaProError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"unknown IN status 0x{status:04x}")


class ParseError(OctaProError):
    pass


class TransportTimeout(OctaProError):
    pass
