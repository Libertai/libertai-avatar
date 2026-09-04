from types import SimpleNamespace

import pytest

from apps.api.visemes import to_visemes


def alignment(phoneme: str, num_samples: int) -> SimpleNamespace:
    return SimpleNamespace(phoneme=phoneme, num_samples=num_samples)


def test_timeline_is_cumulative_in_seconds() -> None:
    timeline = to_visemes([alignment("a", 2205), alignment("i", 4410)], 22050)

    assert [frame.start for frame in timeline] == pytest.approx([0.0, 0.1])
    assert [frame.end for frame in timeline] == pytest.approx([0.1, 0.3])


def test_vowels_map_to_their_vrm_shape_at_full_weight() -> None:
    timeline = to_visemes(
        [alignment("ɑ", 100), alignment("ɛ", 100), alignment("ɪ", 100), alignment("ɔ", 100), alignment("ʊ", 100)],
        22050,
    )

    assert [(frame.viseme, frame.weight) for frame in timeline] == [
        ("aa", 1.0),
        ("ee", 1.0),
        ("ih", 1.0),
        ("oh", 1.0),
        ("ou", 1.0),
    ]


def test_consonants_only_shape_the_mouth_slightly() -> None:
    timeline = to_visemes([alignment("s", 100), alignment("w", 100)], 22050)

    assert [(frame.viseme, frame.weight) for frame in timeline] == [("ih", 0.35), ("ou", 0.35)]


@pytest.mark.parametrize("phoneme", [" ", ",", "ˈ", "p", "b", "m", ""])
def test_silence_and_closed_phonemes_close_the_mouth(phoneme: str) -> None:
    timeline = to_visemes([alignment(phoneme, 100)], 22050)

    assert timeline[0].weight == 0.0


def test_unknown_phonemes_fall_back_to_a_slight_opening() -> None:
    timeline = to_visemes([alignment("ǃ", 100)], 22050)

    assert (timeline[0].viseme, timeline[0].weight) == ("aa", 0.35)


def test_empty_alignments_produce_an_empty_timeline() -> None:
    assert to_visemes([], 22050) == []


def test_invalid_sample_rate_is_rejected() -> None:
    with pytest.raises(ValueError, match="sample_rate must be positive"):
        to_visemes([alignment("a", 100)], 0)
