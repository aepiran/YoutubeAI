from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storyflow_studio.core.settings import AppSettings, TTSSettings
from storyflow_studio.modules.tts import (
    CancellationToken,
    ScreenSubtitleService,
    SingleJobVoiceService,
    TTSDNAService,
    TTSScriptImportService,
    TTSWorkflowCancelled,
    TTSWorkflowError,
    TTSWorkflowService,
    VoiceApiClient,
    VoiceImportService,
)
from storyflow_studio.modules.workspace import WorkspaceService


class FakeAIService:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, Path, object]] = []

    def run(self, prompt, workdir, settings) -> str:
        self.calls.append((prompt, Path(workdir), settings))
        if "<SCREEN_SRT_VERIFICATION>" in prompt:
            return '{"valid": true, "errors": []}'
        if "<NARRATION_SRT>" in prompt:
            return "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n"
        return self.response


class SequenceAIService:
    def __init__(
        self,
        responses: list[str],
        verification_responses: list[str] | None = None,
    ) -> None:
        self.responses = list(responses)
        self.verification_responses = list(verification_responses or [])
        self.calls: list[str] = []

    def run(self, prompt, workdir, settings) -> str:
        self.calls.append(prompt)
        if "<SCREEN_SRT_VERIFICATION>" in prompt:
            if self.verification_responses:
                return self.verification_responses.pop(0)
            return '{"valid": true, "errors": []}'
        return self.responses.pop(0)


class FakeVoiceClient:
    def __init__(self) -> None:
        self.generate_calls: list[tuple[str, TTSSettings]] = []
        self.cancelled: list[str] = []

    def get_balance(self):
        return {"char_balance": 100_000}

    def generate(self, text: str, settings: TTSSettings):
        self.generate_calls.append((text, settings))
        return {"job": {"job_id": "job-001"}}

    def get_job(self, job_id: str):
        return {
            "job": {
                "status": "completed",
                "progress": 100,
                "result": {
                    "audio_url": "/files/narration.mp3",
                    "srt": "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n",
                },
            }
        }

    def cancel_job(self, job_id: str):
        self.cancelled.append(job_id)
        return {"status": "cancelled"}

    def download_audio(self, source: str, destination: Path) -> None:
        destination.write_bytes(b"fake-mp3")

    def download_srt(self, source: str, destination: Path) -> None:
        destination.write_text(source, encoding="utf-8")


class FakeResponse:
    ok = True
    status_code = 200
    text = ""

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class FakeSession:
    def __init__(self) -> None:
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"job_id": "job-http"})


class TTSWorkflowServiceTests(unittest.TestCase):
    def test_screen_subtitles_are_generated_from_script_and_narration_srt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", AppSettings()
            )
            project.path_for("tts_script").write_text(
                "Psalm chapter twenty-three, verse four. Even though I walk "
                "through the darkest valley, I will fear no evil.",
                encoding="utf-8",
            )
            project.path_for("subtitle_file").write_text(
                "1\n00:00:05,000 --> 00:00:10,000\n"
                "Psalm chapter twenty-three, verse four.\n",
                encoding="utf-8",
            )
            ai = SequenceAIService(
                [
                    "1\n00:00:05,000 --> 00:00:10,000\n"
                    "Psalm 23:4\n"
                ]
            )

            result = ScreenSubtitleService(ai).generate(
                project,
                AppSettings().ai,
                lambda _update: None,
                CancellationToken(),
            )

            self.assertEqual(result, project.path_for("screen_subtitle_file"))
            self.assertIn("Psalm 23:4", result.read_text(encoding="utf-8"))
            self.assertIn("<TTS_SCRIPT>", ai.calls[0])
            self.assertIn("<NARRATION_SRT>", ai.calls[0])
            self.assertIn("<SCREEN_SRT_DNA>", ai.calls[0])
            self.assertIn("# StoryFlow Display SRT DNA", ai.calls[0])

    def test_screen_subtitles_retry_when_normal_text_is_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", AppSettings()
            )
            project.path_for("tts_script").write_text(
                "Mercy does not run out.", encoding="utf-8"
            )
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:06,000\n"
                "Mercy does not run out.\n",
                encoding="utf-8",
            )
            ai = SequenceAIService(
                [
                    "1\n00:00:00,000 --> 00:00:06,000\nFresh Mercy\n",
                    "1\n00:00:00,000 --> 00:00:06,000\nMercy does not run out.\n",
                ],
                [
                    '{"valid": false, "errors": ["Ordinary text was rewritten"]}',
                    '{"valid": true, "errors": []}',
                ],
            )

            result = ScreenSubtitleService(ai).generate(
                project,
                AppSettings().ai,
                lambda _update: None,
                CancellationToken(),
            )

            transform_calls = [
                prompt for prompt in ai.calls
                if "<SCREEN_SRT_VERIFICATION>" not in prompt
            ]
            self.assertEqual(len(transform_calls), 2)
            self.assertIn("<PREVIOUS_VALIDATION_ERROR>", transform_calls[1])
            self.assertIn("Mercy does not run out", result.read_text(encoding="utf-8"))

    def test_screen_subtitles_use_custom_dna_from_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", AppSettings()
            )
            project.path_for("tts_script").write_text("Hello world.", encoding="utf-8")
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n",
                encoding="utf-8",
            )
            dna_path = root / "screen-dna.md"
            dna_path.write_text("# My Custom Screen DNA\n", encoding="utf-8")
            ai = FakeAIService("unused")
            service = TTSWorkflowService(ai)

            service.generate_screen_subtitles(
                project,
                AppSettings(tts=TTSSettings(screen_dna_path=str(dna_path))),
                lambda _update: None,
                CancellationToken(),
            )

            self.assertIn("# My Custom Screen DNA", ai.calls[0][0])
            self.assertNotIn("# StoryFlow Display SRT DNA", ai.calls[0][0])

    def test_screen_subtitles_retry_when_a_narration_cue_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", AppSettings()
            )
            project.path_for("tts_script").write_text(
                "Good morning. Mercy is new.", encoding="utf-8"
            )
            project.path_for("subtitle_file").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nGood morning.\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nMercy is new.\n",
                encoding="utf-8",
            )
            ai = SequenceAIService(
                [
                    "1\n00:00:00,000 --> 00:00:01,000\nGood morning.\n",
                    "1\n00:00:00,000 --> 00:00:01,000\nGood morning.\n\n"
                    "2\n00:00:01,000 --> 00:00:02,000\nMercy is new.\n",
                ]
            )

            result = ScreenSubtitleService(ai).generate(
                project,
                AppSettings().ai,
                lambda _update: None,
                CancellationToken(),
            )

            transform_calls = [
                prompt for prompt in ai.calls
                if "<SCREEN_SRT_VERIFICATION>" not in prompt
            ]
            self.assertEqual(len(transform_calls), 2)
            self.assertIn("Mercy is new", result.read_text(encoding="utf-8"))

    def test_screen_subtitles_accept_visual_numeric_conversions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", AppSettings()
            )
            spoken = (
                "In twenty twenty-six, twenty-five dollars covered ten "
                "kilometers and twenty-five percent."
            )
            displayed = "In 2026, $25 covered 10 km and 25%."
            project.path_for("tts_script").write_text(spoken, encoding="utf-8")
            project.path_for("subtitle_file").write_text(
                f"1\n00:00:00,000 --> 00:00:08,000\n{spoken}\n",
                encoding="utf-8",
            )
            ai = SequenceAIService(
                [f"1\n00:00:00,000 --> 00:00:08,000\n{displayed}\n"]
            )

            result = ScreenSubtitleService(ai).generate(
                project,
                AppSettings().ai,
                lambda _update: None,
                CancellationToken(),
            )

            self.assertIn(displayed, result.read_text(encoding="utf-8"))
            verification = next(
                prompt for prompt in ai.calls
                if "<SCREEN_SRT_VERIFICATION>" in prompt
            )
            self.assertIn(spoken, verification)
            self.assertIn(displayed, verification)
            self.assertIn("<SCREEN_SRT_DNA>", verification)

    def test_imports_existing_tts_text_after_fidelity_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Imported TTS", "imported-tts", AppSettings()
            )
            project.path_for("raw_script").write_text(
                "TITLE:\nPrayer\n\nSCRIPT:\nHello world.\nSecond line.",
                encoding="utf-8",
            )
            source = root / "prepared-tts.txt"
            source.write_text("Hello world.\n\nSecond line.\n", encoding="utf-8")

            result = TTSScriptImportService().run(source, project)

            self.assertEqual(result, project.path_for("tts_script"))
            self.assertEqual(
                result.read_text(encoding="utf-8"),
                "Hello world.\n\nSecond line.\n",
            )

    def test_tts_text_import_rejects_changed_script_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Imported TTS", "imported-tts", AppSettings()
            )
            project.path_for("raw_script").write_text("Original words.", encoding="utf-8")
            source = root / "prepared-tts.txt"
            source.write_text("Changed words.", encoding="utf-8")

            with self.assertRaises(TTSWorkflowError):
                TTSScriptImportService().run(source, project)

            self.assertFalse(project.path_for("tts_script").exists())

    def test_imports_existing_audio_and_srt_into_canonical_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Imported Voice", "imported-voice", AppSettings()
            )
            audio_source = root / "source.mp3"
            subtitle_source = root / "source.srt"
            audio_source.write_bytes(b"external-mp3")
            subtitle_source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n",
                encoding="utf-8",
            )
            updates = []

            result = VoiceImportService(duration_probe=lambda _path: 1.0).run(
                audio_source,
                subtitle_source,
                project,
                updates.append,
                CancellationToken(),
            )

            self.assertEqual(result.job_id, "imported")
            self.assertEqual(result.audio_file.read_bytes(), b"external-mp3")
            self.assertIn("Hello world", result.subtitle_file.read_text(encoding="utf-8"))
            self.assertEqual(updates[-1].state, "completed")

    def test_import_rejects_audio_and_srt_with_mismatched_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = WorkspaceService().create_project(
                root / "workspace", "Imported Voice", "imported-voice", AppSettings()
            )
            audio_source = root / "source.mp3"
            subtitle_source = root / "source.srt"
            audio_source.write_bytes(b"external-mp3")
            subtitle_source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n",
                encoding="utf-8",
            )

            with self.assertRaises(TTSWorkflowError):
                VoiceImportService(duration_probe=lambda _path: 60.0).run(
                    audio_source,
                    subtitle_source,
                    project,
                    lambda _update: None,
                    CancellationToken(),
                )

            self.assertFalse(project.path_for("audio_file").exists())
            self.assertFalse(project.path_for("subtitle_file").exists())

    def test_tts_dna_receives_only_content_after_script_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dna_path = root / "tts-dna.md"
            dna_path.write_text("Only adjust line breaks.", encoding="utf-8")
            settings = AppSettings(tts=TTSSettings(dna_path=str(dna_path)))
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", settings
            )
            project.path_for("raw_script").write_text(
                "TITLE:\nMorning Prayer\n\nSCRIPT:\n\nActual narration only.",
                encoding="utf-8",
            )
            ai = FakeAIService("Actual narration only.")
            service = TTSWorkflowService(ai)

            output = service.generate_script(
                project, settings, lambda _update: None, CancellationToken()
            )

            prompt = ai.calls[0][0]
            self.assertNotIn("TITLE:", prompt)
            self.assertNotIn("Morning Prayer", prompt)
            self.assertNotIn("\nSCRIPT:\n", prompt)
            self.assertEqual(
                output.read_text(encoding="utf-8"), "Actual narration only.\n"
            )

    def test_dna_to_single_voice_job_creates_canonical_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dna_path = root / "tts-dna.md"
            dna_path.write_text("Only adjust line breaks.", encoding="utf-8")
            settings = AppSettings(
                tts=TTSSettings(
                    dna_path=str(dna_path),
                    api_base_url="https://voice.example.test",
                    api_key="secret",
                    voice_id="voice-001",
                )
            )
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", settings
            )
            project.path_for("raw_script").write_text(
                "Hello world. Second line.", encoding="utf-8"
            )
            ai = FakeAIService("Hello world.\n\nSecond line.")
            voice_client = FakeVoiceClient()
            service = TTSWorkflowService(
                ai,
                voice_service=SingleJobVoiceService(
                    client_factory=lambda _url, _key: voice_client
                ),
            )
            updates = []

            result = service.run(
                project, settings, updates.append, CancellationToken()
            )

            self.assertEqual(len(ai.calls), 3)
            self.assertEqual(ai.calls[0][1], project.root)
            self.assertIn("Only adjust line breaks.", ai.calls[0][0])
            self.assertEqual(len(voice_client.generate_calls), 1)
            self.assertEqual(
                project.path_for("tts_script").read_text(encoding="utf-8"),
                "Hello world.\n\nSecond line.\n",
            )
            self.assertEqual(result.voice.job_id, "job-001")
            self.assertEqual(result.voice.audio_file.read_bytes(), b"fake-mp3")
            self.assertIn("-->", result.voice.subtitle_file.read_text(encoding="utf-8"))
            self.assertTrue(result.voice.screen_subtitle_file.is_file())
            self.assertIn("<NARRATION_SRT>", ai.calls[1][0])
            self.assertIn("<SCREEN_SRT_VERIFICATION>", ai.calls[2][0])
            self.assertEqual(updates[-1].stage, "voice")
            self.assertEqual(updates[-1].state, "completed")

    def test_script_and_voice_can_be_generated_as_separate_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dna_path = root / "tts-dna.md"
            dna_path.write_text("Only adjust line breaks.", encoding="utf-8")
            settings = AppSettings(
                tts=TTSSettings(
                    dna_path=str(dna_path),
                    api_base_url="https://voice.example.test",
                    api_key="secret",
                    voice_id="voice-001",
                )
            )
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", settings
            )
            project.path_for("raw_script").write_text(
                "Hello world. Second line.", encoding="utf-8"
            )
            client = FakeVoiceClient()
            service = TTSWorkflowService(
                FakeAIService("Hello world.\n\nSecond line."),
                voice_service=SingleJobVoiceService(
                    client_factory=lambda _url, _key: client
                ),
            )

            script_file = service.generate_script(
                project, settings, lambda _update: None, CancellationToken()
            )

            self.assertTrue(script_file.is_file())
            self.assertEqual(client.generate_calls, [])

            voice = service.generate_voice(
                project, settings, lambda _update: None, CancellationToken()
            )

            self.assertEqual(len(client.generate_calls), 1)
            self.assertTrue(voice.audio_file.is_file())
            self.assertTrue(voice.subtitle_file.is_file())

    def test_fidelity_failure_stops_before_voice_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dna_path = root / "dna.md"
            dna_path.write_text("Preserve content.", encoding="utf-8")
            settings = AppSettings(
                tts=TTSSettings(
                    dna_path=str(dna_path),
                    api_base_url="https://voice.example.test",
                    api_key="secret",
                    voice_id="voice-001",
                )
            )
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", settings
            )
            project.path_for("raw_script").write_text("Original words.", encoding="utf-8")
            client = FakeVoiceClient()
            service = TTSWorkflowService(
                FakeAIService("Changed words."),
                voice_service=SingleJobVoiceService(
                    client_factory=lambda _url, _key: client
                ),
            )

            with self.assertRaises(TTSWorkflowError):
                service.run(project, settings, lambda _update: None, CancellationToken())

            self.assertFalse(project.path_for("tts_script").exists())
            self.assertEqual(client.generate_calls, [])

    def test_voice_http_payload_matches_legacy_contract(self) -> None:
        session = FakeSession()
        client = VoiceApiClient(
            "https://voice.example.test/", "secret", session=session
        )
        settings = TTSSettings(
            provider="minimax",
            voice_id="voice-001",
            voice_model="speech-2.8-hd",
            language="English",
            speed=0.935,
            pitch=0,
            volume=1.1,
        )

        response = client.generate("Hello", settings)

        self.assertEqual(response["job_id"], "job-http")
        url, request = session.posts[0]
        self.assertEqual(url, "https://voice.example.test/api/v1/tts/generate")
        self.assertEqual(request["headers"], {"X-API-Key": "secret"})
        self.assertEqual(request["data"]["text"], "Hello")
        self.assertEqual(request["data"]["model"], "speech-2.8-hd")
        self.assertEqual(request["data"]["enable_srt"], "true")

    def test_dna_fidelity_allows_only_whitespace_changes(self) -> None:
        TTSDNAService.validate_fidelity("One two.\nThree.", "One  two.\n\nThree.")
        with self.assertRaises(TTSWorkflowError):
            TTSDNAService.validate_fidelity("One two.", "One changed.")

    def test_cancel_after_job_creation_calls_voice_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = TTSSettings(
                api_base_url="https://voice.example.test",
                api_key="secret",
                voice_id="voice-001",
            )
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", AppSettings(tts=settings)
            )
            client = FakeVoiceClient()
            service = SingleJobVoiceService(
                client_factory=lambda _url, _key: client
            )
            cancellation = CancellationToken()

            def progress(update) -> None:
                if update.job_id:
                    cancellation.cancel()

            with self.assertRaises(TTSWorkflowCancelled):
                service.run("Test script", project, settings, progress, cancellation)

            self.assertEqual(client.cancelled, ["job-001"])
            self.assertFalse(project.path_for("audio_file").exists())

    def test_existing_voice_output_is_not_overwritten_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = TTSSettings(
                api_base_url="https://voice.example.test",
                api_key="secret",
                voice_id="voice-001",
            )
            project = WorkspaceService().create_project(
                root / "workspace", "Story", "story", AppSettings(tts=settings)
            )
            project.path_for("audio_file").write_bytes(b"existing")

            with self.assertRaises(TTSWorkflowError):
                SingleJobVoiceService().validate(project, settings)

            self.assertEqual(project.path_for("audio_file").read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
