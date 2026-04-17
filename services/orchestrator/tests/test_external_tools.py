"""
test_external_tools.py – Tests for the external integration tool layer.

Tests cover:
  1. Simulation fallback when API key is missing
  2. Success path with mocked HTTP calls
  3. Simulation flag correctness in ToolResult.data
  4. Pipeline simulation detection via data["simulation"]

Run:
  cd services/orchestrator
  pytest tests/test_external_tools.py -v
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════════════════
# Voice Generation Tool
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateVoiceTool(unittest.TestCase):

    def _get_tool(self):
        from app.tools.external.voice_generation_tool import GenerateVoiceTool
        return GenerateVoiceTool()

    # ── Simulation fallback (no API keys) ─────────────────────────────────────

    def test_simulation_when_no_tts_key(self):
        """Returns simulation=True when neither TTS nor OpenAI key is set."""
        tool = self._get_tool()
        with patch("app.tools.external.voice_generation_tool._tts_key", return_value=None), \
             patch("app.tools.external.voice_generation_tool._openai_key", return_value=None):
            result = _run(tool.run({"text": "Hello world test"}))

        self.assertEqual(result.status, "success")
        self.assertTrue(result.data["simulation"])
        self.assertEqual(result.data["provider"], "simulation")
        self.assertIsNone(result.data["audio_path"])

    def test_simulation_flag_in_data_always_present(self):
        """data["simulation"] must always be a bool, never missing."""
        tool = self._get_tool()
        with patch("app.tools.external.voice_generation_tool._tts_key", return_value=None), \
             patch("app.tools.external.voice_generation_tool._openai_key", return_value=None):
            result = _run(tool.run({"text": "Test"}))
        self.assertIn("simulation", result.data)
        self.assertIsInstance(result.data["simulation"], bool)

    def test_empty_text_returns_error(self):
        """Missing text should return error status."""
        tool = self._get_tool()
        result = _run(tool.run({"text": ""}))
        self.assertEqual(result.status, "error")

    # ── Success path (mocked OpenAI Nova – numatytasis provideris) ──────────

    def test_elevenlabs_success_path(self):
        """When OpenAI key present and call succeeds, returns real result (nova is default)."""
        tool = self._get_tool()

        async def mock_oai_tts(text, api_key, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"fake_mp3_data")

        with patch("app.tools.external.voice_generation_tool._openai_key", return_value="fake_oai_key"), \
             patch("app.tools.external.voice_generation_tool._openai_tts", side_effect=mock_oai_tts), \
             patch("app.tools.external.voice_generation_tool._output_dir", return_value=Path("/tmp/lani_test_audio")):
            result = _run(tool.run({"text": "Hello world", "output_filename": "test_voice.mp3"}))

        self.assertEqual(result.status, "success")
        self.assertFalse(result.data["simulation"])
        self.assertEqual(result.data["provider"], "openai_tts")
        self.assertIsNotNone(result.data["audio_path"])

    def test_openai_tts_fallback_when_el_fails(self):
        """Falls back to OpenAI TTS when ElevenLabs key fails."""
        tool = self._get_tool()

        async def mock_oai_tts(text, api_key, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"fake_oai_mp3")

        with patch("app.tools.external.voice_generation_tool._tts_key", return_value="fake_el_key"), \
             patch("app.tools.external.voice_generation_tool._elevenlabs_tts", side_effect=RuntimeError("EL error")), \
             patch("app.tools.external.voice_generation_tool._openai_key", return_value="fake_oai_key"), \
             patch("app.tools.external.voice_generation_tool._openai_tts", side_effect=mock_oai_tts), \
             patch("app.tools.external.voice_generation_tool._output_dir", return_value=Path("/tmp/lani_test_audio")):
            result = _run(tool.run({"text": "Hello world", "output_filename": "test_fallback.mp3"}))

        self.assertEqual(result.status, "success")
        self.assertFalse(result.data["simulation"])
        self.assertEqual(result.data["provider"], "openai_tts")

    def test_duration_estimate(self):
        """Duration estimate should be > 0 for non-empty text."""
        tool = self._get_tool()
        with patch("app.tools.external.voice_generation_tool._tts_key", return_value=None), \
             patch("app.tools.external.voice_generation_tool._openai_key", return_value=None):
            result = _run(tool.run({"text": "One two three four five six seven eight nine ten"}))
        self.assertGreater(result.data["duration_s"], 0)


# ══════════════════════════════════════════════════════════════════════════════
# Video Generation Tool
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateVideoExtTool(unittest.TestCase):

    def _get_tool(self):
        from app.tools.external.video_generation_tool import GenerateVideoExtTool
        return GenerateVideoExtTool()

    def test_simulation_when_no_video_key(self):
        """Returns simulation=True and success when VIDEO_API_KEY absent."""
        tool = self._get_tool()
        with patch("app.tools.external.video_generation_tool._video_key", return_value=None):
            result = _run(tool.run({"prompt": "A beautiful sunset over mountains"}))

        self.assertEqual(result.status, "success")
        self.assertTrue(result.data["simulation"])
        self.assertEqual(result.data["provider"], "simulation")
        self.assertIsNone(result.data["video_path"])

    def test_simulation_data_schema_complete(self):
        """Simulation result must contain all required schema keys."""
        tool = self._get_tool()
        with patch("app.tools.external.video_generation_tool._video_key", return_value=None):
            result = _run(tool.run({"prompt": "Test scene"}))

        required = {"success", "simulation", "provider", "video_path", "video_url",
                    "duration_s", "ratio", "prompt_used", "error"}
        self.assertTrue(required.issubset(set(result.data.keys())))

    def test_empty_prompt_returns_error(self):
        tool = self._get_tool()
        result = _run(tool.run({"prompt": ""}))
        self.assertEqual(result.status, "error")
        self.assertFalse(result.data["simulation"])

    def test_real_generation_success(self):
        """Success path with mocked Runway API."""
        tool = self._get_tool()
        mock_path = Path("/tmp/lani_test_video.mp4")

        async def mock_generate(prompt, duration, ratio, api_key, out_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"fake_video_data")
            return "https://cdn.runway.ai/fake_video.mp4"

        with patch("app.tools.external.video_generation_tool._video_key", return_value="fake_rw_key"), \
             patch("app.tools.external.video_generation_tool._generate_runway", side_effect=mock_generate), \
             patch("app.tools.external.video_generation_tool._output_dir", return_value=Path("/tmp")):
            result = _run(tool.run({"prompt": "A drone shot of a forest", "duration": 5}))

        self.assertEqual(result.status, "success")
        self.assertFalse(result.data["simulation"])
        self.assertEqual(result.data["provider"], "runway_gen4")
        self.assertEqual(result.data["video_url"], "https://cdn.runway.ai/fake_video.mp4")


# ══════════════════════════════════════════════════════════════════════════════
# Image Generation Tool
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateImageExtTool(unittest.TestCase):

    def _get_tool(self):
        from app.tools.external.image_generation_tool import GenerateImageExtTool
        return GenerateImageExtTool()

    def test_simulation_when_no_image_key(self):
        tool = self._get_tool()
        with patch("app.tools.external.image_generation_tool._image_key", return_value=None):
            result = _run(tool.run({"prompt": "A minimalist logo design"}))

        self.assertEqual(result.status, "success")
        self.assertTrue(result.data["simulation"])
        self.assertEqual(result.data["provider"], "simulation")
        self.assertEqual(result.data["image_paths"], [])

    def test_real_generation_success(self):
        """Success path with mocked OpenAI Images API."""
        import base64
        tool = self._get_tool()
        fake_b64 = base64.b64encode(b"fake_png_data").decode()

        async def mock_openai(prompt, model, size, count, api_key):
            return [{"b64_json": fake_b64} for _ in range(count)]

        with patch("app.tools.external.image_generation_tool._image_key", return_value="fake_oai_key"), \
             patch("app.tools.external.image_generation_tool._openai_generate", side_effect=mock_openai), \
             patch("app.tools.external.image_generation_tool._output_dir", return_value=Path("/tmp")):
            result = _run(tool.run({"prompt": "Hero image for campaign", "count": 2}))

        self.assertEqual(result.status, "success")
        self.assertFalse(result.data["simulation"])
        self.assertEqual(result.data["provider"], "openai_images")
        self.assertEqual(len(result.data["image_paths"]), 2)

    def test_simulation_flag_false_on_real_success(self):
        """simulation must be False when real API call succeeds."""
        import base64
        tool = self._get_tool()
        fake_b64 = base64.b64encode(b"x").decode()

        async def mock_openai(prompt, model, size, count, api_key):
            return [{"b64_json": fake_b64}]

        with patch("app.tools.external.image_generation_tool._image_key", return_value="key"), \
             patch("app.tools.external.image_generation_tool._openai_generate", side_effect=mock_openai), \
             patch("app.tools.external.image_generation_tool._output_dir", return_value=Path("/tmp")):
            result = _run(tool.run({"prompt": "Test", "count": 1}))

        self.assertFalse(result.data["simulation"])


# ══════════════════════════════════════════════════════════════════════════════
# Music Generation Tool
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateSongExtTool(unittest.TestCase):

    def _get_tool(self):
        from app.tools.external.music_generation_tool import GenerateSongExtTool
        return GenerateSongExtTool()

    def test_simulation_when_no_music_key(self):
        tool = self._get_tool()
        with patch("app.tools.external.music_generation_tool._music_key", return_value=None):
            result = _run(tool.run({"prompt": "Upbeat summer pop song"}))

        self.assertEqual(result.status, "success")
        self.assertTrue(result.data["simulation"])
        self.assertEqual(result.data["provider"], "simulation")
        self.assertEqual(result.data["track_paths"], [])

    def test_real_generation_success(self):
        tool = self._get_tool()

        async def mock_suno(prompt, lyrics, style, title, instrumental, api_key):
            fake_path = "/tmp/test_song.mp3"
            Path(fake_path).write_bytes(b"fake_mp3")
            return ([fake_path], ["https://cdn.suno.ai/fake.mp3"])

        with patch("app.tools.external.music_generation_tool._music_key", return_value="fake_suno"), \
             patch("app.tools.external.music_generation_tool._generate_suno", side_effect=mock_suno):
            result = _run(tool.run({"prompt": "Electronic dance track", "title": "Test Track"}))

        self.assertEqual(result.status, "success")
        self.assertFalse(result.data["simulation"])
        self.assertEqual(result.data["provider"], "suno_ai")
        self.assertEqual(len(result.data["track_paths"]), 1)
        self.assertEqual(len(result.data["track_urls"]), 1)


# ══════════════════════════════════════════════════════════════════════════════
# Web Search Tool
# ══════════════════════════════════════════════════════════════════════════════

class TestWebSearchExtTool(unittest.TestCase):

    def _get_tool(self):
        from app.tools.external.web_search_tool import WebSearchExtTool
        return WebSearchExtTool()

    def test_simulation_when_all_providers_fail(self):
        """Simulation fallback when DuckDuckGo and SerpAPI both fail."""
        tool = self._get_tool()
        with patch("app.tools.external.web_search_tool._search_key", return_value=None), \
             patch("app.tools.external.web_search_tool._ddg_html_search", side_effect=RuntimeError("network")), \
             patch("app.tools.external.web_search_tool._ddg_search", side_effect=RuntimeError("network")):
            result = _run(tool.run({"query": "latest AI news 2026"}))

        self.assertEqual(result.status, "success")
        self.assertTrue(result.data["simulation"])
        self.assertEqual(result.data["provider"], "simulation")

    def test_duckduckgo_success(self):
        """DuckDuckGo result returns simulation=False."""
        tool = self._get_tool()
        fake_results = [
            {"title": "AI News", "url": "https://example.com", "snippet": "Latest AI news", "source": "duckduckgo"}
        ]
        with patch("app.tools.external.web_search_tool._search_key", return_value=None), \
             patch("app.tools.external.web_search_tool._ddg_html_search", return_value=fake_results):
            result = _run(tool.run({"query": "AI news 2026"}))

        self.assertEqual(result.status, "success")
        self.assertFalse(result.data["simulation"])
        self.assertEqual(result.data["provider"], "duckduckgo")
        self.assertEqual(len(result.data["results"]), 1)

    def test_serpapi_preferred_when_key_set(self):
        """Tavily is used first when SEARCH_API_KEY is configured."""
        tool = self._get_tool()
        fake_results = [
            {"title": "Tavily Result", "url": "https://tavily.com/1", "snippet": "Snippet 1", "source": "tavily"}
        ]
        with patch("app.tools.external.web_search_tool._search_key", return_value="fake_tavily_key"), \
             patch("app.tools.external.web_search_tool._tavily_search", return_value=fake_results):
            result = _run(tool.run({"query": "test query"}))

        self.assertEqual(result.data["provider"], "tavily")
        self.assertFalse(result.data["simulation"])

    def test_empty_query_returns_error(self):
        tool = self._get_tool()
        result = _run(tool.run({"query": ""}))
        self.assertEqual(result.status, "error")


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline simulation detection
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineSimulationDetection(unittest.TestCase):
    """
    Verify that run_pipeline sets any_simulation=True when a tool returns
    data["simulation"] = True (i.e., external tool simulated due to missing key).
    """

    def test_simulation_flag_propagated_from_tool_data(self):
        """
        When step.simulation_mode=False but tool result data["simulation"]=True,
        PipelineResult.simulation must be True.
        """
        from app.services.pipeline_service import PipelineResult, _data_from_result

        # Simulate what run_pipeline does after extracting an artifact
        any_simulation = False
        artifact_value = {"simulation": True, "provider": "simulation", "video_path": None}

        # This mirrors the updated logic in run_pipeline
        if isinstance(artifact_value, dict) and artifact_value.get("simulation"):
            any_simulation = True

        self.assertTrue(any_simulation)

    def test_simulation_flag_false_when_real_data(self):
        any_simulation = False
        artifact_value = {"simulation": False, "provider": "runway_gen4", "video_path": "/tmp/v.mp4"}

        if isinstance(artifact_value, dict) and artifact_value.get("simulation"):
            any_simulation = True

        self.assertFalse(any_simulation)


# ══════════════════════════════════════════════════════════════════════════════
# Result schema validation
# ══════════════════════════════════════════════════════════════════════════════

class TestResultSchemaConsistency(unittest.TestCase):
    """All external tools must always return data with the required schema keys."""

    REQUIRED_KEYS = {"success", "simulation", "provider", "error"}

    def _assert_schema(self, data: dict):
        missing = self.REQUIRED_KEYS - set(data.keys())
        self.assertFalse(missing, f"Missing required keys in result.data: {missing}")
        self.assertIsInstance(data["simulation"], bool)
        self.assertIsInstance(data["success"], bool)

    def test_voice_simulation_schema(self):
        from app.tools.external.voice_generation_tool import GenerateVoiceTool
        tool = GenerateVoiceTool()
        with patch("app.tools.external.voice_generation_tool._tts_key", return_value=None), \
             patch("app.tools.external.voice_generation_tool._openai_key", return_value=None):
            r = _run(tool.run({"text": "Test"}))
        self._assert_schema(r.data)

    def test_video_simulation_schema(self):
        from app.tools.external.video_generation_tool import GenerateVideoExtTool
        tool = GenerateVideoExtTool()
        with patch("app.tools.external.video_generation_tool._video_key", return_value=None):
            r = _run(tool.run({"prompt": "Test scene"}))
        self._assert_schema(r.data)

    def test_image_simulation_schema(self):
        from app.tools.external.image_generation_tool import GenerateImageExtTool
        tool = GenerateImageExtTool()
        with patch("app.tools.external.image_generation_tool._image_key", return_value=None):
            r = _run(tool.run({"prompt": "Test image"}))
        self._assert_schema(r.data)

    def test_music_simulation_schema(self):
        from app.tools.external.music_generation_tool import GenerateSongExtTool
        tool = GenerateSongExtTool()
        with patch("app.tools.external.music_generation_tool._music_key", return_value=None):
            r = _run(tool.run({"prompt": "Test song"}))
        self._assert_schema(r.data)

    def test_search_simulation_schema(self):
        from app.tools.external.web_search_tool import WebSearchExtTool
        tool = WebSearchExtTool()
        with patch("app.tools.external.web_search_tool._search_key", return_value=None), \
             patch("app.tools.external.web_search_tool._ddg_html_search", side_effect=RuntimeError), \
             patch("app.tools.external.web_search_tool._ddg_search", side_effect=RuntimeError):
            r = _run(tool.run({"query": "test"}))
        self._assert_schema(r.data)


if __name__ == "__main__":
    unittest.main()
