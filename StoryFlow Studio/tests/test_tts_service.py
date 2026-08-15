from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storyflow_studio.core.settings import AppSettings, TTSSettings
from storyflow_studio.modules.tts import (
    CancellationToken,
    SingleJobVoiceService,
    TTSDNAService,
    TTSWorkflowCancelled,
    TTSWorkflowError,
    TTSWorkflowService,
    VoiceApiClient,
)
from storyflow_studio.modules.workspace import WorkspaceService


class FakeAIService:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, Path, object]] = []

    def run(self, prompt, workdir, settings) -> str:
        self.calls.append((prompt, Path(workdir), settings))
        return self.response


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

            self.assertEqual(len(ai.calls), 1)
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
            self.assertEqual(updates[-1].stage, "voice")
            self.assertEqual(updates[-1].state, "completed")

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
