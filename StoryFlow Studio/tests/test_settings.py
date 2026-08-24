from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from storyflow_studio.core.settings import (
    AISettings,
    AppSettings,
    BeatSettings,
    FootageSettings,
    MusicSettings,
    SettingsStore,
    TTSSettings,
    VideoBuilderSettings,
    WorkspaceSettings,
)


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str:
        return self.values.get(name, "")

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class SettingsStoreTests(unittest.TestCase):
    def test_round_trip_ai_settings_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            store.save_ai(AISettings("gpt-5.6-terra", "high"))

            self.assertEqual(store.load_ai(), AISettings("gpt-5.6-terra", "high"))
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(raw), {"schema_version", "ai"})
            self.assertNotIn("api_key", path.read_text(encoding="utf-8").lower())

    def test_invalid_reasoning_effort_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                '{"ai":{"model":" custom ","reasoning_effort":"invalid"}}',
                encoding="utf-8",
            )
            self.assertEqual(
                SettingsStore(path).load_ai(),
                AISettings("custom", "default"),
            )

    def test_round_trip_ai_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            store.save_ai(AISettings("claude-opus-5", "high", "claude"))

            self.assertEqual(
                store.load_ai(), AISettings("claude-opus-5", "high", "claude")
            )
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["ai"]["provider"], "claude")

    def test_invalid_ai_provider_falls_back_to_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                '{"ai":{"model":"custom","provider":"unknown"}}',
                encoding="utf-8",
            )
            self.assertEqual(
                SettingsStore(path).load_ai(),
                AISettings("custom", "default", "codex"),
            )

    def test_full_settings_round_trip_keeps_api_key_out_of_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            secrets = MemorySecretStore()
            store = SettingsStore(path, secrets)
            settings = AppSettings(
                ai=AISettings("gpt-5.6-sol", "high"),
                workspace=WorkspaceSettings(
                    workspace_root="/projects",
                    role_file="/roles/writer.md",
                    role_instructions="Write with a calm voice.",
                    recent_projects=["/projects/one"],
                    last_project="/projects/one",
                    workflow_mode="auto",
                ),
                tts=TTSSettings(
                    dna_path="/dna/voice.md",
                    screen_dna_path="/dna/screen.md",
                    api_base_url="https://voice.example.test/",
                    api_key="top-secret-value",
                    voice_id="voice-01",
                    output_folder="voice",
                ),
                beat=BeatSettings("/dna/beat.md", "beats.csv"),
                music=MusicSettings(
                    "/dna/music.md",
                    "/music/library",
                    True,
                ),
                footage=FootageSettings(
                    use_pexels=True,
                    use_pixabay=True,
                    pexels_api_key="pexels-secret",
                    pixabay_api_key="pixabay-secret",
                    clips_per_beat=3,
                ),
                video_builder=VideoBuilderSettings(
                    resolution="720p",
                    output_fps=60,
                    min_cut_seconds=2.5,
                    target_cut_seconds=4.5,
                    max_cut_seconds=6.5,
                    transition_seconds=0.25,
                    encoder_preset="fast",
                    visual_model="google/siglip2-base-patch16-224",
                    local_models_only=False,
                    scene_threshold=0.4,
                    scene_min_seconds=1.5,
                    capcut_template_dir="/capcut/template",
                    capcut_drafts_root="/capcut/drafts",
                    capcut_register_draft=True,
                ),
            )

            store.save(settings)
            loaded = store.load()

            raw_text = path.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
            self.assertNotIn("top-secret-value", raw_text)
            self.assertNotIn("api_key", raw["tts"])
            self.assertNotIn("voice_name", raw["tts"])
            self.assertEqual(secrets.values["tts_api_key"], "top-secret-value")
            self.assertEqual(loaded.tts.api_key, "top-secret-value")
            self.assertEqual(loaded.tts.api_base_url, "https://voice.example.test")
            self.assertEqual(loaded.tts.screen_dna_path, "/dna/screen.md")
            self.assertEqual(loaded.workspace.last_project, "/projects/one")
            self.assertEqual(loaded.workspace.workflow_mode, "auto")
            self.assertEqual(loaded.beat.output_filename, "beats.csv")
            self.assertEqual(loaded.music.dna_path, "/dna/music.md")
            self.assertEqual(loaded.music.library_folder, "/music/library")
            self.assertTrue(loaded.music.enabled)
            self.assertEqual(
                raw["music"]["library_folder"], "/music/library"
            )
            self.assertNotIn("output_filename", raw["music"])
            self.assertTrue(raw["music"]["enabled"])
            self.assertNotIn("pexels-secret", raw_text)
            self.assertNotIn("pixabay-secret", raw_text)
            self.assertNotIn("pexels_api_key", raw["footage"])
            self.assertNotIn("pixabay_api_key", raw["footage"])
            self.assertEqual(loaded.footage.pexels_api_key, "pexels-secret")
            self.assertEqual(loaded.footage.pixabay_api_key, "pixabay-secret")
            self.assertEqual(loaded.footage.clips_per_beat, 3)
            self.assertEqual(loaded.video_builder.resolution, "720p")
            self.assertEqual(loaded.video_builder.output_fps, 60)
            self.assertEqual(loaded.video_builder.target_cut_seconds, 4.5)
            self.assertEqual(loaded.video_builder.encoder_preset, "fast")
            self.assertEqual(
                loaded.video_builder.visual_model,
                "google/siglip2-base-patch16-224",
            )
            self.assertFalse(loaded.video_builder.local_models_only)
            self.assertEqual(loaded.video_builder.scene_threshold, 0.4)
            self.assertEqual(
                loaded.video_builder.capcut_template_dir, "/capcut/template"
            )
            self.assertEqual(
                loaded.video_builder.capcut_drafts_root, "/capcut/drafts"
            )
            self.assertTrue(loaded.video_builder.capcut_register_draft)


if __name__ == "__main__":
    unittest.main()
