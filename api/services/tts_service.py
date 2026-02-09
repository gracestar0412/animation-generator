"""TTS (Text-to-Speech) service for Bible Animation narration."""

import asyncio
import os
import re
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("tts_service")

DEFAULT_VOICE = "ko-KR-SunHiNeural"

# Language → Edge-TTS voice mapping
VOICE_MAP = {
    "en": "en-US-AndrewNeural",       # English male narrator
    "ko": "ko-KR-SunHiNeural",        # Korean female narrator
    "ja": "ja-JP-NanamiNeural",        # Japanese female narrator
    "zh": "zh-CN-XiaoxiaoNeural",      # Chinese female narrator
    "es": "es-ES-AlvaroNeural",        # Spanish male narrator
}


def get_voice_for_language(language: str) -> str:
    """Get the appropriate Edge-TTS voice for a given language code."""
    lang = language.lower().strip()
    # Handle full locale codes like "en-US"
    if "-" in lang:
        lang = lang.split("-")[0]
    return VOICE_MAP.get(lang, DEFAULT_VOICE)

# ----- Text Preprocessing -----

def preprocess_text_for_tts(text: str) -> str:
    """
    Preprocess narration text for TTS:
    - Remove stage directions [brackets]
    - Remove markdown formatting
    - Clean up whitespace
    """
    # Remove bracketed stage directions
    text = re.sub(r'\[.*?\]|\(.*?\)', '', text)
    # Remove markdown
    text = re.sub(r'[\*_#]+', '', text)
    # Clean whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ----- Google Cloud TTS Config -----

PROJECT_ID = os.getenv("PROJECT_ID", "")
DEFAULT_CREDENTIALS_PATH = os.path.join(os.getcwd(), "shorts.json")
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", DEFAULT_CREDENTIALS_PATH)
SCOPES = ['https://www.googleapis.com/auth/cloud-platform']


def get_google_creds(scopes):
    """Get Google Cloud credentials."""
    try:
        from google.oauth2 import service_account
        if os.path.exists(CREDENTIALS_PATH):
            return service_account.Credentials.from_service_account_file(
                CREDENTIALS_PATH, scopes=scopes
            )
    except Exception as e:
        logger.warning(f"Failed to load Google credentials: {e}")
    return None


# ----- Main TTS Function -----

async def generate_tts(
    text: str,
    output_path: str,
    voice: str = DEFAULT_VOICE,
) -> Tuple[bool, str, Optional[str]]:
    """
    Generate TTS audio + VTT subtitles.
    
    Returns: (success: bool, message: str, vtt_path: Optional[str])
    """
    try:
        # Preprocess text
        clean_text = preprocess_text_for_tts(text)
        if not clean_text:
            return False, "Empty text after preprocessing", None

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Generate audio with Edge-TTS
        success = await generate_edge_audio(clean_text, output_path, voice)
        if not success:
            return False, "Edge-TTS generation failed", None

        # Generate VTT subtitles
        vtt_path = output_path.replace(".mp3", ".vtt")
        vtt_success = await generate_vtt_from_audio(output_path, clean_text, vtt_path)

        if not vtt_success:
            # Create a simple fallback VTT
            create_simple_vtt(clean_text, output_path, vtt_path)

        return True, "Success", vtt_path

    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        return False, str(e), None


async def generate_edge_audio(text: str, output_path: str, voice: str, rate: str = "+0%") -> bool:
    """Generate audio using Edge-TTS."""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(output_path)
        # Verify file was created and has content
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            logger.info(f"✅ Edge-TTS audio generated: {os.path.basename(output_path)}")
            return True
        else:
            logger.error(f"Edge-TTS produced empty/small file")
            return False
    except Exception as e:
        logger.error(f"Edge-TTS failed: {e}")
        return False


async def generate_vtt_from_audio(audio_path: str, text: str, vtt_path: str) -> bool:
    """
    Generate VTT subtitles using Gemini (audio transcription with timestamps).
    Falls back to simple VTT if Gemini is unavailable.
    """
    try:
        from google import genai
        import json
        import base64

        creds = get_google_creds(SCOPES)
        if not creds:
            return False

        client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location="global"
        )

        # Read audio file
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        audio_b64 = base64.b64encode(audio_data).decode("utf-8")

        prompt = f"""You are a precise audio transcription tool.
Listen to this audio and provide word-level timestamps.

The text spoken is:
"{text}"

Return a JSON array of cue objects:
[
  {{"start_ms": 0, "end_ms": 1500, "text": "첫 번째 구절"}},
  {{"start_ms": 1500, "end_ms": 3000, "text": "두 번째 구절"}}
]

Rules:
- Split into natural phrase groups (3-8 words each)
- Timestamps must be precise to the audio
- Cover the entire audio duration
- Return ONLY the JSON array
"""

        from google.genai import types

        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=[
                types.Content(parts=[
                    types.Part(text=prompt),
                    types.Part(inline_data=types.Blob(
                        mime_type="audio/mpeg",
                        data=audio_data
                    ))
                ])
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )
        )

        cues = json.loads(response.text)
        vtt_content = create_vtt_from_cues(cues)

        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write(vtt_content)

        logger.info(f"✅ VTT generated via Gemini: {os.path.basename(vtt_path)}")
        return True

    except Exception as e:
        logger.warning(f"Gemini VTT generation failed: {e}")
        return False


def create_vtt_from_cues(cues: list) -> str:
    """Convert cue list to WebVTT format."""
    def ms_to_vtt_time(ms):
        s, ms_rem = divmod(int(ms), 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}.{ms_rem:03d}"

    lines = ["WEBVTT", ""]
    for i, cue in enumerate(cues, 1):
        start = ms_to_vtt_time(cue["start_ms"])
        end = ms_to_vtt_time(cue["end_ms"])
        lines.append(str(i))
        lines.append(f"{start} --> {end}")
        lines.append(cue["text"])
        lines.append("")

    return "\n".join(lines)


def create_simple_vtt(text: str, audio_path: str, vtt_path: str):
    """Create a simple fallback VTT by splitting text evenly over audio duration."""
    import subprocess

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True
        )
        duration_ms = int(float(result.stdout.strip()) * 1000)
    except Exception:
        duration_ms = 10000  # fallback 10 seconds

    # Split text into sentences
    sentences = re.split(r'(?<=[.!?。])\s+', text)
    if not sentences:
        sentences = [text]

    per_sentence_ms = duration_ms // len(sentences)

    cues = []
    for i, sentence in enumerate(sentences):
        cues.append({
            "start_ms": i * per_sentence_ms,
            "end_ms": (i + 1) * per_sentence_ms,
            "text": sentence.strip()
        })

    vtt_content = create_vtt_from_cues(cues)
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write(vtt_content)

    logger.info(f"✅ Simple VTT created: {os.path.basename(vtt_path)}")
