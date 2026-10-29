"""Shared stdlib GDSII record reader for the layout/ evidence scripts."""
from __future__ import annotations

import struct


class GdsError(ValueError):
    pass


def gds_real(b: bytes) -> float:
    """GDSII 8-byte excess-64 real."""
    sign = -1.0 if b[0] & 0x80 else 1.0
    mant = int.from_bytes(b[1:], "big") / float(1 << 56)
    return sign * mant * 16.0 ** ((b[0] & 0x7F) - 64)


def gds_records(data: bytes):
    """Yield (record type, data type, body); raise GdsError on a malformed stream."""
    i, n = 0, len(data)
    while i < n:
        if i + 4 > n:
            raise GdsError(f"truncated record header at byte {i}")
        length, rtype, dtype = struct.unpack(">HBB", data[i:i + 4])
        if length < 4 or i + length > n:
            raise GdsError(f"bad record length {length} at byte {i}")
        yield rtype, dtype, data[i + 4:i + length]
        i += length
        if rtype == 0x04:  # ENDLIB
            rest = data[i:]
            if rest.strip(b"\x00"):
                raise GdsError(f"non-padding bytes after ENDLIB at byte {i}")
            return
    raise GdsError("no ENDLIB record")
