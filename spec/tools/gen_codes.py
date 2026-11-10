"""Write spec/codes.json. Standalone on purpose (no server import): the vectors are an
independent statement of the code rules that the server and the app both test against.

    python3 spec/tools/gen_codes.py
"""

from __future__ import annotations

import json
from pathlib import Path

ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
N = 30

# Sample payloads (7 chars); the check character is appended below.
SAMPLE_PAYLOADS = ["HG4N7KQ", "NB2XW9D", "2222222", "ZZZZZZZ", "M3T8RCA", "QV5JYPF", "K2ZM4PX"]


def luhn_check(payload: str) -> str:
    """Luhn mod N, as on https://en.wikipedia.org/wiki/Luhn_mod_N_algorithm."""
    factor = 2
    total = 0
    for ch in reversed(payload):
        addend = factor * ALPHABET.index(ch)
        factor = 1 if factor == 2 else 2
        total += addend // N + addend % N
    return ALPHABET[(N - total % N) % N]


def luhn_valid(code: str) -> bool:
    factor = 1
    total = 0
    for ch in reversed(code):
        addend = factor * ALPHABET.index(ch)
        factor = 1 if factor == 2 else 2
        total += addend // N + addend % N
    return total % N == 0


def main() -> None:
    samples = [p + luhn_check(p) for p in SAMPLE_PAYLOADS]
    valid = []
    for code in samples:
        shown = f"{code[:4]}-{code[4:]}"
        for raw in {shown, code, shown.lower(), f" {code[:4]} {code[4:]} ", f"{code[:2]}-{code[2:]}\n"}:
            valid.append({"input": raw, "code": code, "display": shown})
    valid.sort(key=lambda v: (v["code"], v["input"]))

    invalid = [
        {"input": "", "error": "bad_format", "reason": "length"},
        {"input": "HG4N-7KQ", "error": "bad_format", "reason": "length"},
        {"input": samples[0] + "2", "error": "bad_format", "reason": "length"},
        {"input": "----  ----", "error": "bad_format", "reason": "length"},
        {"input": "HG4O-7KQE", "error": "bad_format", "reason": "confusable"},
        {"input": "HG40-7KQE", "error": "bad_format", "reason": "confusable"},
        {"input": "HGIN-7KQE", "error": "bad_format", "reason": "confusable"},
        {"input": "HG1N-7KQE", "error": "bad_format", "reason": "confusable"},
        {"input": "HGLN-7KQE", "error": "bad_format", "reason": "confusable"},
        {"input": "HGUN-7KQE", "error": "bad_format", "reason": "confusable"},
        {"input": "hgun-7kqe", "error": "bad_format", "reason": "confusable"},
        {"input": "HG4N_7KQE", "error": "bad_format", "reason": "length"},
        {"input": "HG4N.7KQE", "error": "bad_format", "reason": "length"},
        {"input": "HG4N#7KQ", "error": "bad_format", "reason": "char"},
        {"input": "HG4Ñ-7KQE", "error": "bad_format", "reason": "char"},
        {"input": "HG4N 7KQE", "error": "bad_format", "reason": "length"},
        {"input": "ＨG4N-7KQE", "error": "bad_format", "reason": "char"},
    ]

    typos = []
    for code in samples:
        for pos in range(8):
            for ch in ALPHABET:
                if ch == code[pos]:
                    continue
                typo = code[:pos] + ch + code[pos + 1 :]
                assert not luhn_valid(typo)
                typos.append({"input": typo, "of": code, "position": pos})

    transpositions = []
    for code in samples:
        for pos in range(7):
            if code[pos] == code[pos + 1]:
                continue
            swapped = code[:pos] + code[pos + 1] + code[pos] + code[pos + 2 :]
            transpositions.append(
                {"input": swapped, "of": code, "position": pos,
                 "result": "valid" if luhn_valid(swapped) else "bad_check"}
            )

    out = {
        "description": (
            "Route code vectors. Normalise: upper-case ASCII a-z, remove U+0020 U+0009 U+000A "
            "U+000D and '-'. Then: length != 8 -> bad_format/length; a character outside the "
            "alphabet -> bad_format/confusable if it is one of O 0 I 1 L U, else bad_format/char "
            "(first offending character decides); wrong Luhn mod 30 check -> bad_check."
        ),
        "alphabet": ALPHABET,
        "length": 8,
        "samples": samples,
        "valid": valid,
        "invalid": invalid,
        "singleCharTypos": {
            "description": "Every substitution of one character of each sample by another "
            "alphabet character; every one must fail with bad_check.",
            "error": "bad_check",
            "cases": typos,
        },
        "adjacentTranspositions": {
            "description": "Swaps of two neighbouring different characters. Luhn mod 30 misses "
            "some of them; `result` is what a correct implementation returns.",
            "cases": transpositions,
        },
    }
    path = Path(__file__).resolve().parents[1] / "codes.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(samples)} samples, {len(valid)} valid, {len(invalid)} invalid, "
          f"{len(typos)} typos, {len(transpositions)} transpositions "
          f"({sum(t['result'] == 'valid' for t in transpositions)} undetected)")


if __name__ == "__main__":
    main()
