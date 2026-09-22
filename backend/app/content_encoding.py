"""Which content codings a request accepts, read the way RFC 9110 §12.5.3 says.

A substring test on `Accept-Encoding` takes `gzip;q=0` - "anything but gzip" -
for a yes. Every place that chooses an encoding for a response asks here.
"""
from __future__ import annotations


def accepts_encoding(header: str | None, coding: str) -> bool:
    """Whether `coding` is acceptable: named with a weight above zero, or not
    named while `*` is. An absent header accepts nothing but identity here,
    which is the safe reading for a server choosing to compress."""
    if not header:
        return False
    coding = coding.lower()
    named: float | None = None
    wildcard: float | None = None
    for item in header.split(","):
        token, _, parameters = item.strip().partition(";")
        weight = 1.0
        for parameter in parameters.split(";"):
            name, _, value = parameter.strip().partition("=")
            if name.strip().lower() == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        token = token.strip().lower()
        if token == coding:
            named = weight
        elif token == "*":
            wildcard = weight
    if named is not None:
        return named > 0
    return wildcard is not None and wildcard > 0
