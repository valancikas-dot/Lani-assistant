"""
external/ – Real API integration tools for Lani's pipeline execution system.

Each tool in this package:
  • follows the BaseTool interface (.run(params) → ToolResult)
  • checks for an API key at runtime
  • if the key is present → makes the real external call
  • if the key is absent → returns a clearly-marked simulation stub
  • always sets result.data["simulation"] = True/False
  • NEVER fakes external API success

Tool names
──────────
  generate_voice       – ElevenLabs TTS → OpenAI TTS → simulation
  generate_video_ext   – Runway ML → simulation (wraps video_tool)
  generate_image_ext   – OpenAI Images → simulation (wraps image_tool)
  generate_song_ext    – Suno AI → simulation (wraps music_tool)
  web_search_ext       – DuckDuckGo → SerpAPI → simulation

Env vars consumed
──────────────────
  TTS_API_KEY          – alias for ELEVENLABS_API_KEY (ElevenLabs preferred)
  VIDEO_API_KEY        – alias for RUNWAY_API_KEY
  IMAGE_API_KEY        – alias for OPENAI_API_KEY (image sub-key or same)
  MUSIC_API_KEY        – alias for SUNO_API_KEY
  SEARCH_API_KEY       – SerpAPI key (DuckDuckGo is used without a key)
"""
