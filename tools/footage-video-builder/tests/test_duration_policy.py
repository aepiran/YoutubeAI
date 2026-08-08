import unittest
from dataclasses import replace

from video_builder.config import default_config
from video_builder.duration_policy import extend_with_silent_outro
from video_builder.models import Beat, SpeechSegment


class MinimumDurationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.beat = Beat(
            number=1,
            code="B001",
            main_idea="peaceful closing prayer",
            keywords="sunrise lake nature",
            desired_visual="quiet nature at dawn",
            avoid="indoor, dramatic action",
        )

    def _segment(self, end: float) -> SpeechSegment:
        return SpeechSegment(
            index=0,
            beats=(self.beat,),
            text="Amen.",
            start=0.0,
            end=end,
            section_index=1,
            section_name="Benediction",
        )

    def test_short_audio_gets_nature_only_cuts_to_25_minutes(self) -> None:
        config = replace(default_config(), minimum_video_seconds=1500.0)
        segments, added = extend_with_silent_outro(
            config, [self._segment(1470.0)], 1470.0
        )

        self.assertEqual(added, 30.0)
        self.assertEqual(segments[-1].end, 1500.0)
        self.assertTrue(all(item.duration <= 7.0 for item in segments[1:]))
        self.assertTrue(all(item.section_name == "DWG OUTRO" for item in segments[1:]))
        self.assertTrue(all(item.beat_codes == "B001" for item in segments[1:]))

    def test_audio_at_or_over_minimum_is_not_changed(self) -> None:
        config = replace(default_config(), minimum_video_seconds=1500.0)
        original = [self._segment(1500.0)]

        equal_segments, equal_added = extend_with_silent_outro(
            config, original, 1500.0
        )
        long_segments, long_added = extend_with_silent_outro(
            config, original, 1520.0
        )

        self.assertIs(equal_segments, original)
        self.assertEqual(equal_added, 0.0)
        self.assertIs(long_segments, original)
        self.assertEqual(long_added, 0.0)

    def test_zero_disables_minimum_duration(self) -> None:
        config = replace(default_config(), minimum_video_seconds=0.0)
        original = [self._segment(1470.0)]
        segments, added = extend_with_silent_outro(config, original, 1470.0)

        self.assertIs(segments, original)
        self.assertEqual(added, 0.0)


if __name__ == "__main__":
    unittest.main()
