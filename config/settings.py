import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(exist_ok=True)

# GCP / AI Settings
PROJECT_ID = os.getenv("PROJECT_ID", "")
CREDENTIALS_PATH = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    str(BASE_DIR / "shorts.json")
)

# Video Config (16:9 Landscape for longform)
VIDEO_CONFIG = {
    "width": 1920,
    "height": 1080,
    "fps": 24,
    "font": "Arial",
    "fontsize": 14,
    "color": "white",
    "stroke_color": "black",
    "stroke_width": 1,
}

# TTS Config
TTS_CONFIG = {
    "default_voice": "ko-KR-SunHiNeural",
    "rate": "+0%",
}

# Bible Animation Defaults
BIBLE_CONFIG = {
    "default_style": "pixar_disney",
    "target_duration_minutes": 10.0,
    "max_scenes": 60,
    "scene_duration_range": (5, 15),  # seconds
    "character_db_path": str(BASE_DIR / "data" / "character_db.json"),
}

# ============================================================================
# STYLE PRESETS — configurable visual style for video prompt generation
# Each preset provides:
#   - style_anchor: injected into video_prompt.style for every scene
#   - negative: injected into video_prompt.negative for drift prevention
#   - subtitle_font / subtitle_size: render-time subtitle appearance
# ============================================================================
STYLE_PRESETS = {
    "pixar_disney": {
        "name": "Pixar / Disney 3D Animation",
        "style_anchor": (
            "Pixar-quality 3D animation rendered in Disney animated feature film style "
            "with soft subsurface scattering skin shading and large expressive eyes "
            "and stylized proportions and warm saturated color palette and volumetric "
            "god-ray lighting and cinematic depth of field, "
            "biblical epic setting, 4K ultra-detailed"
        ),
        "negative": (
            "distorted face, asymmetric eyes, extra limbs, deformed hands, "
            "cloned face, duplicate characters, photorealistic style, anime style, "
            "flat 2D illustration, watermark, text overlay"
        ),
        "subtitle_font": "Arial",
        "subtitle_size": 14,
    },
    "ark_films": {
        "name": "Ark Films (Cinematic Bible)",
        "style_anchor": (
            "4K cinematic 3D biblical animation, photorealistic painterly textures, "
            "dramatic volumetric god-ray lighting, emotionally expressive faces, "
            "epic scale, Ark Films / Prince of Egypt quality"
        ),
        "negative": (
            "cartoon style, flat illustration, anime style, "
            "distorted face, extra limbs, deformed hands, watermark"
        ),
        "subtitle_font": "Pretendard",
        "subtitle_size": 28,
    },
    "watercolor": {
        "name": "Watercolor Bible Illustration",
        "style_anchor": (
            "Beautiful watercolor painting style with soft washes and visible brush strokes "
            "and delicate line work and warm earthy tones and gentle diffused lighting, "
            "biblical storybook illustration, hand-painted quality, 4K detailed"
        ),
        "negative": (
            "3D render, photorealistic, harsh shadows, neon colors, "
            "distorted face, extra limbs, modern elements, watermark"
        ),
        "subtitle_font": "Georgia",
        "subtitle_size": 20,
    },
    "stained_glass": {
        "name": "Stained Glass Cathedral",
        "style_anchor": (
            "Medieval stained glass window art style with rich jewel-tone colors "
            "and bold black outlines and luminous translucent quality as if backlit "
            "by cathedral sunlight, sacred religious art, 4K detailed"
        ),
        "negative": (
            "photorealistic, 3D render, soft edges, modern style, "
            "distorted face, extra limbs, watermark"
        ),
        "subtitle_font": "Times New Roman",
        "subtitle_size": 22,
    },
}


def get_style_preset(name: str) -> dict:
    """Get a style preset by name. Falls back to pixar_disney."""
    preset = STYLE_PRESETS.get(name)
    if not preset:
        available = ", ".join(STYLE_PRESETS.keys())
        raise ValueError(f"Unknown style preset: '{name}'. Available: {available}")
    return preset
