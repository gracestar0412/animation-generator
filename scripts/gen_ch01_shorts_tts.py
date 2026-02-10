"""Generate TTS audio + VTT for ch01 shorts narration scenes."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.services.tts_service import generate_tts, get_voice_for_language


async def main():
    ch01_dir = "data/projects/david_and_goliath/ch01_the_shepherd_king_chosen"
    shorts_script_path = os.path.join(ch01_dir, "shorts_script.json")
    assets_shorts_dir = os.path.join(ch01_dir, "assets_shorts")

    os.makedirs(assets_shorts_dir, exist_ok=True)

    with open(shorts_script_path, "r", encoding="utf-8") as f:
        shorts_script = json.load(f)

    scenes = shorts_script["scenes"]
    voice = get_voice_for_language("en")  # English narration
    
    print(f"🗣️ Generating TTS for {len(scenes)} shorts scenes")
    print(f"   Voice: {voice}")
    print(f"   Output: {assets_shorts_dir}")
    print()

    # Track mapping for asset_mapping.json
    mapping = {"scenes": {}}
    success_count = 0

    for scene in scenes:
        sid = scene["id"]
        narration = scene.get("narration", "")

        mp3_name = f"shorts_audio_{sid:03d}.mp3"
        vtt_name = f"shorts_audio_{sid:03d}.vtt"
        mp3_path = os.path.join(assets_shorts_dir, mp3_name)
        vtt_path = os.path.join(assets_shorts_dir, vtt_name)

        if not narration.strip():
            print(f"⏭️ Scene {sid}: No narration (hook/SFX only)")
            mapping["scenes"][str(sid)] = {
                "mp3": mp3_name,
                "vtt": vtt_name,
                "has_tts": False,
                "narration": ""
            }
            continue

        # Skip if already generated
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 1024:
            print(f"⏭️ Scene {sid}: TTS already exists")
            mapping["scenes"][str(sid)] = {
                "mp3": mp3_name,
                "vtt": vtt_name,
                "has_tts": True,
                "narration": narration[:60]
            }
            success_count += 1
            continue

        print(f"🗣️ Scene {sid}: Generating TTS...")
        print(f"   Text: {narration[:80]}...")

        success, msg, _ = await generate_tts(narration, mp3_path, voice=voice)

        if success:
            success_count += 1
            print(f"✅ Scene {sid}: TTS complete → {mp3_name}")
            mapping["scenes"][str(sid)] = {
                "mp3": mp3_name,
                "vtt": vtt_name,
                "has_tts": True,
                "narration": narration[:60]
            }
        else:
            print(f"❌ Scene {sid}: TTS failed - {msg}")
            mapping["scenes"][str(sid)] = {
                "mp3": mp3_name,
                "vtt": vtt_name,
                "has_tts": False,
                "narration": narration[:60],
                "error": msg
            }

    # Save asset mapping
    mapping_path = os.path.join(assets_shorts_dir, "asset_mapping.json")
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    print(f"\n✅ TTS Generation Complete: {success_count}/{len(scenes)} scenes")
    print(f"📋 Asset mapping: {mapping_path}")


if __name__ == "__main__":
    asyncio.run(main())
