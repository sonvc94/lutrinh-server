"""Canonical JSON (RFC 8785, JSON Canonicalization Scheme) for ``route.json``.

A published ``route.json`` is stored and served as exactly these bytes, and its sha256 is the
package hash (ETag, ``route_links.package_sha256`` in the app). Rules:

* UTF-8, no whitespace, no trailing newline;
* object keys sorted by their UTF-16 code units;
* strings: only ``"`` ``\\`` and U+0000..U+001F are escaped (``\\b \\t \\n \\f \\r``, else
  ``\\u00xx`` lower-case); everything else is written as is;
* numbers: ECMAScript ``Number.prototype.toString`` (``5.0`` → ``5``, ``1e-7`` → ``1e-7``,
  ``1e21`` → ``1e+21``); integers must stay within ±(2**53 − 1); NaN/Infinity are rejected.

Vectors: ``spec/canonical-json.json``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

MAX_SAFE_INTEGER = 2**53 - 1

_SHORT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _string(s: str) -> str:
    out = ['"']
    for ch in s:
        esc = _SHORT_ESCAPES.get(ch)
        if esc is not None:
            out.append(esc)
        elif ch < " ":
            out.append(f"\\u{ord(ch):04x}")
        elif "\ud800" <= ch <= "\udfff":
            raise ValueError("lone surrogate in string")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _float(x: float) -> str:
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError("NaN and Infinity are not JSON")
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    # repr() gives the shortest round-trip digits, as ECMAScript does.
    _, digits_t, exp = Decimal(repr(abs(x))).as_tuple()
    assert isinstance(exp, int)
    digits = "".join(map(str, digits_t)).rstrip("0")
    exp += len(digits_t) - len(digits)
    k = len(digits)
    n = k + exp  # value = 0.<digits> × 10**n
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
        body = f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + body


def _encode(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError(f"integer outside the safe range: {value}")
        out.append(str(value))
    elif isinstance(value, float):
        out.append(_float(value))
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, dict):
        out.append("{")
        keys = list(value)
        if not all(isinstance(k, str) for k in keys):
            raise TypeError("object keys must be strings")
        for i, key in enumerate(sorted(keys, key=lambda k: k.encode("utf-16-be"))):
            if i:
                out.append(",")
            out.append(_string(key))
            out.append(":")
            _encode(value[key], out)
        out.append("}")
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _encode(item, out)
        out.append("]")
    else:
        raise TypeError(f"not JSON-serialisable: {type(value).__name__}")


def dumps(value: Any) -> bytes:
    """Canonical UTF-8 bytes of a JSON value."""
    out: list[str] = []
    _encode(value, out)
    return "".join(out).encode("utf-8")


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, val in pairs:
        if key in obj:
            raise ValueError(f"duplicate key: {key!r}")
        obj[key] = val
    return obj


def _parse_int(text: str) -> int | float:
    # JSON numbers are IEEE-754 doubles (RFC 8785): integers beyond 2**53 - 1 become floats,
    # so "64010633007109840" written for a large double reads back as the same double.
    value = int(text)
    return value if abs(value) <= MAX_SAFE_INTEGER else float(value)


def loads(data: bytes | str) -> Any:
    """Strict parse: no NaN/Infinity, no duplicate keys; numbers as doubles (safe ints stay int)."""
    return json.loads(
        data,
        parse_constant=_reject_constant,
        parse_int=_parse_int,
        object_pairs_hook=_no_duplicates,
    )


def canonicalise(data: bytes | str) -> bytes:
    """Parse any JSON text and return its canonical bytes."""
    return dumps(loads(data))
