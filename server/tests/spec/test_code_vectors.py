"""spec/codes.json against lutrinh.core.codes."""

from __future__ import annotations

import pytest

from lutrinh.core import codes
from tests.conftest import load_spec

V = load_spec("codes.json")


def test_alphabet_matches_spec() -> None:
    assert V["alphabet"] == codes.ALPHABET
    assert V["length"] == codes.CODE_LENGTH


@pytest.mark.parametrize("case", V["valid"], ids=lambda c: repr(c["input"]))
def test_valid_codes_parse(case: dict[str, str]) -> None:
    code = codes.parse(case["input"])
    assert code == case["code"]
    assert codes.display(code) == case["display"]


@pytest.mark.parametrize("case", V["invalid"], ids=lambda c: repr(c["input"]))
def test_invalid_codes_rejected(case: dict[str, str]) -> None:
    with pytest.raises(codes.CodeError) as err:
        codes.parse(case["input"])
    assert err.value.kind == case["error"]
    assert err.value.reason == case.get("reason")


def test_every_single_char_typo_of_the_samples_is_rejected() -> None:
    cases = V["singleCharTypos"]["cases"]
    assert len(cases) == len(V["samples"]) * 8 * (len(codes.ALPHABET) - 1)
    for case in cases:
        with pytest.raises(codes.CodeError) as err:
            codes.parse(case["input"])
        assert err.value.kind == "bad_check", case


def test_adjacent_transpositions_match_spec() -> None:
    for case in V["adjacentTranspositions"]["cases"]:
        try:
            codes.parse(case["input"])
            got = "valid"
        except codes.CodeError as err:
            got = err.kind
        assert got == case["result"], case


def test_sample_check_characters() -> None:
    for sample in V["samples"]:
        assert codes.check_char(sample[:7]) == sample[7]
