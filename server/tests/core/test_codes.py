from __future__ import annotations

import random

import pytest

from lutrinh.core import codes


def test_1000_random_codes_parse_and_round_trip() -> None:
    rng = random.Random(20261110)
    seen = set()
    for _ in range(1000):
        code = codes.generate(rng=rng)
        seen.add(code)
        assert len(code) == 8 and set(code) <= set(codes.ALPHABET)
        shown = codes.display(code)
        assert codes.parse(shown) == code
        assert codes.parse(shown.lower()) == code
        assert codes.parse(f" {code[:4]} {code[4:]} ") == code
    assert len(seen) == 1000


def test_csprng_codes_are_valid() -> None:
    for _ in range(200):
        assert codes.parse(codes.generate()) is not None


def test_every_single_char_typo_of_random_codes_is_rejected() -> None:
    rng = random.Random(7)
    for _ in range(50):
        code = codes.generate(rng=rng)
        for pos in range(8):
            for ch in codes.ALPHABET:
                if ch != code[pos]:
                    with pytest.raises(codes.CodeError) as err:
                        codes.parse(code[:pos] + ch + code[pos + 1 :])
                    assert err.value.kind == "bad_check"


def test_prefix_is_kept_and_rest_is_random() -> None:
    rng = random.Random(1)
    got = {codes.generate("hg", rng=rng) for _ in range(100)}
    assert all(c.startswith("HG") and codes.parse(c) == c for c in got)
    assert len(got) == 100


@pytest.mark.parametrize("prefix", ["H", "HGX", "H0", "U2", ""])
def test_bad_prefix(prefix: str) -> None:
    with pytest.raises(ValueError):
        codes.generate(prefix)


def test_error_str() -> None:
    assert str(codes.CodeError("bad_format", "confusable")) == "bad_format:confusable"
    assert str(codes.CodeError("bad_check")) == "bad_check"
