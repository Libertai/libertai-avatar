"""Map Piper's IPA phoneme alignments onto the five VRM mouth expressions.

VRM defines only ``aa``, ``ih``, ``ou``, ``ee`` and ``oh``, so every phoneme collapses onto
the nearest of those. Vowels drive the mouth fully; consonants only shape it slightly, and
silence closes it.
"""

from __future__ import annotations

from typing import Iterable, NamedTuple

VOWELS = {
    "aa": "aɑɐʌæɒ",
    "ee": "ɛeøœ",
    "ih": "iɪɨy",
    "oh": "oɔɜɚɝ",
    "ou": "uʊ",
}

# Consonants barely open the mouth, but the shape still reads: rounded, spread, or closed.
CONSONANTS = {
    "ou": "wɹrʃʒ",
    "ih": "ijsztdnlθðkgŋ",
    "ee": "fv",
}

CLOSED = "pbm"
SILENCE = " ^$,.;:!?\"'ˈˌː\n\t"

VOWEL_WEIGHT = 1.0
CONSONANT_WEIGHT = 0.35


class Viseme(NamedTuple):
    viseme: str
    weight: float
    start: float
    end: float


def _shape_for(phoneme: str) -> tuple[str, float]:
    """Return the VRM expression and weight a phoneme should produce."""
    if not phoneme or phoneme in SILENCE:
        return ("aa", 0.0)
    if phoneme in CLOSED:
        return ("aa", 0.0)

    for viseme, members in VOWELS.items():
        if phoneme in members:
            return (viseme, VOWEL_WEIGHT)
    for viseme, members in CONSONANTS.items():
        if phoneme in members:
            return (viseme, CONSONANT_WEIGHT)
    return ("aa", CONSONANT_WEIGHT)


def to_visemes(alignments: Iterable, sample_rate: int) -> list[Viseme]:
    """Convert phoneme alignments into a timeline of VRM mouth shapes.

    Args:
        alignments: Piper ``PhonemeAlignment`` items, in order, each with ``num_samples``.
        sample_rate: Sample rate of the synthesized audio, used to turn samples into seconds.

    Returns:
        Visemes with absolute start and end times in seconds.
    """
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}")

    timeline: list[Viseme] = []
    elapsed = 0.0
    for alignment in alignments:
        duration = alignment.num_samples / sample_rate
        viseme, weight = _shape_for(alignment.phoneme)
        timeline.append(Viseme(viseme=viseme, weight=weight, start=elapsed, end=elapsed + duration))
        elapsed += duration

    return timeline
