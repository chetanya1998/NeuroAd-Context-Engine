import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import attention_label, make_segments, score_attention


def test_segmentation_short_video_uses_two_second_chunks():
    segments = make_segments(10)
    assert len(segments) == 5
    assert segments[0]["end"] == 2


def test_segmentation_caps_long_video_at_three_minutes():
    segments = make_segments(900)
    assert segments[-1]["end"] == 180


def test_attention_score_is_bounded():
    assert score_attention(2, 2, 2, 2, 2, 2, 2) == 100
    assert score_attention(-2, -2, -2, -2, -2, -2, -2) == 0


def test_attention_labels():
    assert attention_label(85) == "High attention"
    assert attention_label(65) == "Good attention"
    assert attention_label(45) == "Neutral"
    assert attention_label(25) == "Drop risk"
    assert attention_label(10) == "Weak moment"
