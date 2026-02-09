"""
King David 1-Minute Demo Production.
Reference style: Ark Films Channel (https://www.youtube.com/@ArkFilmsChannel)
- 4K cinematic 3D Bible animation
- Emotional, character-driven storytelling
- Dramatic volumetric lighting, expressive facial close-ups
- KJV-inspired narration for US audience
"""

import asyncio
import json
import os
import sys
import subprocess
import logging
import uuid

# Setup
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("demo")

from api.utils.paths import PathManager
from api.production.character_db import CharacterDB

# ---- CONFIG ----
RUN_ID = "david_" + str(uuid.uuid4())[:6]
MAX_SCENE_DURATION = 7.9  # seconds (< 8s for Veo)
TTS_VOICE = "en-US-AndrewNeural"  # Warm, Confident, Authentic — storyteller
TTS_RATE = "-5%"  # slightly slower for gravitas
TARGET_DURATION = 60  # 1 minute

pm = PathManager(RUN_ID)
pm.ensure_dirs()

logger.info(f"🎬 Run ID: {RUN_ID}")
logger.info(f"📁 Output: {pm.root}")


def get_audio_duration(path: str) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except:
        return 0.0


async def generate_master_script():
    """Phase 1: Generate the full script via Gemini in one shot."""
    logger.info("📖 Phase 1: Generating master script...")

    from google import genai
    from google.genai import types
    from google.oauth2 import service_account

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./shorts.json")
    project_id = os.getenv("PROJECT_ID", "rare-style-481210-p3")
    SCOPES = ['https://www.googleapis.com/auth/cloud-platform']

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = genai.Client(credentials=creds, vertexai=True, project=project_id, location="global")

    # Character descriptions
    char_db = CharacterDB()
    david_desc = char_db.get_prompt_fragment("david")
    goliath_desc = (
        "Goliath: A towering, terrifying giant warrior, over 9 feet tall with a "
        "thick muscular build. A scarred, brutal face with cruel dark eyes and a "
        "heavy brow. Wearing full bronze armor — a massive bronze helmet, a coat of "
        "bronze scale armor, bronze greaves on his legs. Carrying an enormous iron-tipped "
        "spear like a weaver's beam and a large bronze shield borne by a shield-bearer."
    )

    prompt = f"""
You are an expert Bible animation scriptwriter creating a short film in the style of 
"Ark Films Channel" — known for stunning, cinematic 3D animated Bible movies.

REFERENCE STYLE (from Ark Films Channel):
- 4K cinematic 3D animation with painterly, photorealistic textures
- Deeply emotional, character-driven storytelling — not just events, but FEELINGS
- Hook the viewer with a provocative emotional question (e.g., "What if the strongest man who ever lived was also the loneliest?")
- Dramatic volumetric lighting (god-rays, golden hour, torch-lit interiors)
- Expressive character close-ups that show inner emotion
- Grand wide shots for scale and awe
- Style reminiscent of "Prince of Egypt" meets modern 3D animation

TASK: Write a 1-minute (60 seconds) dramatic narration about David vs Goliath.
Base on the King James Version (KJV) of 1 Samuel 17.

CHARACTER DESCRIPTIONS (USE THESE EXACTLY in video prompts):
{david_desc}

{goliath_desc}

CRITICAL RULES:
1. Each scene narration MUST be speakable in UNDER 7 SECONDS.
   - That means 1-2 sentences, roughly 12-20 words per scene.
2. Generate 8-10 scenes for approximately 60 seconds total.
3. Narration is in English — dramatic, reverent, KJV-inspired tone.
   - Feel like a warm, wise narrator telling the most epic story ever told.
   - Open with an emotional hook that makes the viewer NEED to keep watching.
   - You may paraphrase KJV text.
4. Story arc:
   - Scene 1: Emotional opening hook (provoke curiosity)
   - Scene 2-3: Establish the terror of Goliath and Israel's fear
   - Scene 4-5: David's arrival and faith
   - Scene 6-7: The confrontation moment
   - Scene 8-9: The sling, the stone, the fall
   - Scene 10: Powerful closing statement

VIDEO PROMPT STYLE GUIDE:
- "objects" must include FULL character descriptions provided above
- "style" should emphasize: "4K cinematic 3D biblical animation, photorealistic painterly textures, 
  dramatic volumetric god-ray lighting, emotionally expressive character faces, 
  epic scale, Ark Films / Prince of Egypt quality"
- Use close-ups on faces to show EMOTION (fear, courage, faith, desperation)
- Use wide establishing shots for scale (the valley, the armies)
- Include dramatic weather and lighting shifts to match emotional beats

OUTPUT FORMAT (strict JSON):
{{
  "title": "David and Goliath",
  "scenes": [
    {{
      "id": 1,
      "narration": "Short, powerful English narration (under 7 seconds spoken).",
      "video_prompt": {{
        "objects": "Full character descriptions + environment details",
        "action": "What physically happens — movements, expressions, gestures",
        "style": "4K cinematic 3D biblical animation, photorealistic painterly textures, dramatic volumetric god-ray lighting, emotionally expressive faces, epic scale",
        "camera": "Specific shot type and movement (close-up, wide, aerial, tracking, etc.)",
        "atmosphere": "Emotional mood, weather, time of day, lighting quality",
        "sfx": "Specific sound effects for this moment"
      }}
    }}
  ]
}}
"""

    config = types.GenerateContentConfig(
        temperature=0.85,
        response_mime_type="application/json",
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=config,
    )

    raw_text = response.text

    # Clean up common JSON issues from Gemini (trailing commas, etc.)
    import re
    cleaned = re.sub(r',\s*([}\]])', r'\1', raw_text)  # Remove trailing commas
    cleaned = cleaned.strip()
    if cleaned.startswith("```"):
        # Remove markdown code fences if present
        cleaned = re.sub(r'^```json?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)

    script = json.loads(cleaned)

    with open(pm.script_file, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    logger.info(f"✅ Master script: {len(script['scenes'])} scenes")
    for s in script["scenes"]:
        logger.info(f"  Scene {s['id']}: \"{s['narration']}\"")

    return script


async def generate_tts_for_scenes(scenes: list):
    """Phase 2: Generate TTS for each scene, measure durations."""
    import edge_tts

    logger.info(f"🗣️ Phase 2: Generating TTS ({TTS_VOICE}, rate={TTS_RATE})...")
    results = []

    for scene in scenes:
        idx = scene["id"]
        narration = scene.get("narration", "")
        audio_path = pm.get_audio_path(idx)

        logger.info(f"  Scene {idx}: \"{narration[:60]}\"")

        communicate = edge_tts.Communicate(narration, TTS_VOICE, rate=TTS_RATE)
        await communicate.save(audio_path)

        duration = get_audio_duration(audio_path)
        scene["tts_duration"] = duration
        status = '✅' if duration < MAX_SCENE_DURATION else '⚠️ OVER'
        logger.info(f"    → {duration:.2f}s {status}")

        results.append({
            "id": idx,
            "narration": narration,
            "tts_duration": duration,
            "audio_path": audio_path,
            "within_limit": duration < MAX_SCENE_DURATION,
        })

    return results


async def fix_long_scenes(script: dict, tts_results: list):
    """Phase 3: Trim scenes exceeding 8 seconds (up to 3 rounds)."""
    long_scenes = [r for r in tts_results if not r["within_limit"]]

    if not long_scenes:
        logger.info("✅ All scenes within 8-second limit!")
        return script, tts_results

    logger.info(f"⚠️ {len(long_scenes)} scenes exceed {MAX_SCENE_DURATION}s, trimming...")

    from google import genai
    from google.genai import types
    from google.oauth2 import service_account
    import edge_tts

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "./shorts.json")
    project_id = os.getenv("PROJECT_ID", "rare-style-481210-p3")
    SCOPES = ['https://www.googleapis.com/auth/cloud-platform']
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = genai.Client(credentials=creds, vertexai=True, project=project_id, location="global")

    for round_num in range(3):
        still_long = [r for r in tts_results if not r["within_limit"]]
        if not still_long:
            break

        logger.info(f"  Trim round {round_num + 1}: {len(still_long)} scenes to fix")

        for r in still_long:
            scene_id = r["id"]
            scene = next(s for s in script["scenes"] if s["id"] == scene_id)

            prompt = f"""
This English narration takes {r['tts_duration']:.1f}s when spoken. It MUST be under 6.5 seconds.

Original: "{r['narration']}"

Make it shorter while keeping the KJV-inspired dramatic impact.
Return ONLY the shortened text, nothing else. No quotes around it.
"""
            config = types.GenerateContentConfig(temperature=0.3)
            response = client.models.generate_content(
                model="gemini-2.5-flash", contents=prompt, config=config,
            )
            new_narration = response.text.strip().strip('"').strip("'")

            audio_path = pm.get_audio_path(scene_id)
            communicate = edge_tts.Communicate(new_narration, TTS_VOICE, rate=TTS_RATE)
            await communicate.save(audio_path)

            new_duration = get_audio_duration(audio_path)
            status = '✅' if new_duration < MAX_SCENE_DURATION else '⚠️'
            logger.info(f"    Scene {scene_id}: {r['tts_duration']:.1f}s → {new_duration:.1f}s {status}")

            scene["narration"] = new_narration
            scene["tts_duration"] = new_duration
            r["tts_duration"] = new_duration
            r["narration"] = new_narration
            r["within_limit"] = new_duration < MAX_SCENE_DURATION

    with open(pm.script_file, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    return script, tts_results


async def generate_vtt_subtitles(scenes: list):
    """Phase 4: Generate VTT subtitle files."""
    from api.services.tts_service import create_simple_vtt

    logger.info("📝 Phase 4: Generating VTT subtitles...")
    for scene in scenes:
        idx = scene["id"]
        narration = scene.get("narration", "")
        create_simple_vtt(narration, pm.get_audio_path(idx), pm.get_vtt_path(idx))
    logger.info("✅ VTT subtitles generated")


def output_scene_prompts(script: dict):
    """Phase 5: Output scene prompts for user."""
    from api.services.prompts import format_scene_prompts_txt

    prompts_text = format_scene_prompts_txt(script["scenes"])
    with open(pm.scene_prompts_file, "w", encoding="utf-8") as f:
        f.write(prompts_text)

    logger.info("")
    logger.info("=" * 70)
    logger.info("🎬 SCENE VIDEO PROMPTS — David and Goliath (KJV / Ark Films Style)")
    logger.info("=" * 70)

    for scene in script["scenes"]:
        idx = scene["id"]
        dur = scene.get("tts_duration", 0)
        vp = scene.get("video_prompt", {})

        logger.info("")
        logger.info(f"─── Scene {idx} (TTS: {dur:.1f}s) ───")
        logger.info(f"  NARRATION: \"{scene.get('narration', '')}\"")
        if isinstance(vp, dict):
            for key in ["objects", "action", "style", "camera", "atmosphere", "sfx"]:
                if vp.get(key):
                    logger.info(f"  {key.upper()}: {vp[key]}")

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"📝 Prompts file:  {pm.scene_prompts_file}")
    logger.info(f"🎵 Audio files:   {pm.assets}")
    logger.info(f"📁 Place videos:  {pm.scenes}")
    logger.info(f"   Expected:      scene_001.mp4, scene_002.mp4, ...")
    logger.info(f"🔄 Resume:        ./run_bible.sh --resume {RUN_ID}")
    logger.info("=" * 70)


def print_summary(script: dict, tts_results: list):
    """Print final summary."""
    logger.info("")
    logger.info("📊 FINAL SCENE SUMMARY")
    logger.info(f"{'#':>3} {'Duration':>9} {'OK':>4}  Narration")
    logger.info("-" * 70)

    total_dur = 0
    for r in tts_results:
        status = "✅" if r["within_limit"] else "⚠️"
        total_dur += r["tts_duration"]
        logger.info(f"{r['id']:>3} {r['tts_duration']:>7.2f}s {status:>4}  \"{r['narration'][:55]}\"")

    logger.info("-" * 70)
    logger.info(f"    {total_dur:>7.2f}s total ({total_dur/60:.1f} min)")
    logger.info("")


async def main():
    logger.info("🎬 David & Goliath — 1-Min Demo (KJV / US / Ark Films Style)")
    logger.info(f"📁 Run: {pm.root}")
    logger.info("")

    script = await generate_master_script()
    tts_results = await generate_tts_for_scenes(script["scenes"])
    script, tts_results = await fix_long_scenes(script, tts_results)
    await generate_vtt_subtitles(script["scenes"])

    print_summary(script, tts_results)
    output_scene_prompts(script)

    logger.info("✅ Done! Create scene videos from the prompts above.")


if __name__ == "__main__":
    asyncio.run(main())
