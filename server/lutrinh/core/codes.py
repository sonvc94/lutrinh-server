"""Route codes: ``XXXX-XXXX``, 30-character alphabet, last character = Luhn mod 30 check.

Rules (shared with the app through ``spec/codes.json``):

* alphabet ``23456789ABCDEFGHJKMNPQRSTVWXYZ`` (no 0/O, 1/I/L, U), value of a character =
  its index in the alphabet;
* 8 characters; the 8th is the Luhn mod N (N = 30) check character of the first 7;
* input is normalised before checking: ASCII letters are upper-cased, and space, tab, CR, LF and
  hyphen-minus are removed; nothing else is rewritten (a ``0`` is never read as ``O``);
* errors: ``bad_format`` (reason ``length``, ``confusable`` = one of O 0 I 1 L U, ``char`` = any
  other character outside the alphabet) and ``bad_check`` (8 alphabet characters, wrong check).

The checks run before any database lookup; they cost nothing and catch every single-character
typo.
"""

from __future__ import annotations

import secrets
from random import Random
from typing import Literal

ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
N = len(ALPHABET)
CODE_LENGTH = 8
PAYLOAD_LENGTH = CODE_LENGTH - 1
PREFIX_LENGTH = 2
CONFUSABLE = frozenset("O0I1LU")
_IGNORED = frozenset(" \t\r\n-")
_VALUE = {c: i for i, c in enumerate(ALPHABET)}

assert N == 30

ErrorKind = Literal["bad_format", "bad_check"]
Reason = Literal["length", "confusable", "char"]


class CodeError(ValueError):
    """A code that cannot be valid. ``kind`` matches the public API error codes."""

    def __init__(self, kind: ErrorKind, reason: Reason | None = None) -> None:
        super().__init__(kind, reason)
        self.kind: ErrorKind = kind
        self.reason: Reason | None = reason

    def __str__(self) -> str:
        return self.kind if self.reason is None else f"{self.kind}:{self.reason}"


def _addend(value: int, double: bool) -> int:
    if not double:
        return value
    doubled = value * 2
    return doubled // N + doubled % N


def check_char(payload: str) -> str:
    """Luhn mod 30 check character for 7 alphabet characters (already normalised)."""
    total = 0
    # The rightmost payload character is doubled, then every second one leftwards.
    for i, ch in enumerate(reversed(payload)):
        total += _addend(_VALUE[ch], double=(i % 2 == 0))
    return ALPHABET[(N - total % N) % N]


def is_check_valid(code: str) -> bool:
    """True if 8 normalised alphabet characters carry a correct check character."""
    total = 0
    for i, ch in enumerate(reversed(code)):
        total += _addend(_VALUE[ch], double=(i % 2 == 1))
    return total % N == 0


def normalise(raw: str) -> str:
    """Upper-case ASCII letters and drop separators. Does not validate."""
    out = []
    for ch in raw:
        if ch in _IGNORED:
            continue
        out.append(ch.upper() if "a" <= ch <= "z" else ch)
    return "".join(out)


def parse(raw: str) -> str:
    """Normalise and validate; return the 8-character canonical code or raise ``CodeError``."""
    code = normalise(raw)
    if len(code) != CODE_LENGTH:
        raise CodeError("bad_format", "length")
    for ch in code:
        if ch not in _VALUE:
            raise CodeError("bad_format", "confusable" if ch in CONFUSABLE else "char")
    if not is_check_valid(code):
        raise CodeError("bad_check")
    return code


def display(code: str) -> str:
    """``HG4N7KQE`` → ``HG4N-7KQE`` (expects a parsed code)."""
    return f"{code[:4]}-{code[4:]}"


def generate(prefix: str | None = None, rng: Random | None = None) -> str:
    """New random code (CSPRNG unless ``rng`` is given, for tests). Returns the canonical form.

    ``prefix``: optional 2 alphabet characters chosen by the admin (``HG``); the other payload
    characters stay random.
    """
    chooser = rng if rng is not None else secrets.SystemRandom()
    head = ""
    if prefix is not None:
        head = normalise(prefix)
        if len(head) != PREFIX_LENGTH or any(c not in _VALUE for c in head):
            raise ValueError(f"prefix must be {PREFIX_LENGTH} characters of {ALPHABET}")
    payload = head + "".join(chooser.choice(ALPHABET) for _ in range(PAYLOAD_LENGTH - len(head)))
    return payload + check_char(payload)
