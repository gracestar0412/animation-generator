"""
Bible Animation Orchestrator.
Main pipeline: Script → TTS → [User provides videos] → Render → Merge → Metadata.
"""

import asyncio
import os
import sys
import json
import re
import shutil
import logging
import subprocess
import time
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from api.utils.paths import PathManager, ProjectPathManager, ChapterPathManager
from api.production.project_manager import ProjectManager, slugify
from api.services.ai import AIClient
from api.services.tts_service import generate_tts, preprocess_text_for_tts, get_voice_for_language
from api.production.script_generator import ScriptGenerator
from api.production.character_db import CharacterDB
from api.production.validators import (
    validate_audio_asset, validate_video_asset, validate_vtt_asset,
    validate_scene_videos, get_duration
)
from config.settings import get_style_preset, STYLE_PRESETS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("BibleOrchestrator")


def _parse_duration_target(duration_str: str) -> float:
    """Parse duration string like '2m30s', '1m', '90s' to minutes (float)."""
    import re as _re
    minutes = 0.0
    m_match = _re.search(r'(\d+)\s*m', duration_str)
    s_match = _re.search(r'(\d+)\s*s', duration_str)
    if m_match:
        minutes += int(m_match.group(1))
    if s_match:
        minutes += int(s_match.group(1)) / 60.0
    return minutes if minutes > 0 else 2.0  # default 2 min


def run_cmd(cmd):
    """Execute shell command."""
    try:
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        if isinstance(cmd, list):
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE,
                           stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
        else:
            subprocess.run(cmd, shell=True, check=True, stderr=subprocess.PIPE,
                           stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError as e:
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        logger.error(f"Command failed: {cmd_str}\nStderr: {e.stderr.decode()}")
        return False


class BibleOrchestrator:
    """
    Main orchestrator for Bible animation production.
    
    Workflow:
    1. Script Generation (AI + CharacterDB)
    2. TTS Generation (all scenes)
    3. Pause for user to produce scene videos
    4. Render (combine scene video + TTS + subtitles)
    5. Merge all clips into master video
    6. Generate YouTube metadata
    """

    def __init__(
        self,
        run_id: Optional[str] = None,
        book: Optional[str] = None,
        chapter: Optional[str] = None,
        target_duration: float = 10.0,
        style_preset: str = "pixar_disney",
        path_manager=None,
    ):
        self.book = book
        self.chapter = chapter
        self.target_duration = target_duration
        self.style_preset_name = style_preset
        self.style = get_style_preset(style_preset)

        # Generate or use provided run ID
        self.run_id = run_id or str(uuid.uuid4())[:8]

        # Path manager — use provided (project mode) or create default (legacy runs mode)
        if path_manager:
            self.pm = path_manager
        else:
            self.pm = PathManager(self.run_id)
        self.pm.ensure_dirs()

        # Services
        self.ai = AIClient()
        self.char_db = CharacterDB()
        self.script_gen = ScriptGenerator(
            ai_client=self.ai,
            character_db=self.char_db,
            style_preset=style_preset,
        )

        # State
        self.script_data = None
        self.scenes = []
        self.chapter_context = None  # Set externally for project-mode chapters
        self.shorts_mode = False  # 9:16 shorts rendering mode

        logger.info(f"🎬 BibleOrchestrator initialized. Run ID: {self.run_id}")
        logger.info(f"🎨 Style: {self.style['name']}")
        logger.info(f"📁 Run directory: {self.pm.root}")

    def _load_existing_script(self) -> bool:
        """Load script from disk if it exists (for resume)."""
        if os.path.exists(self.pm.script_file):
            try:
                with open(self.pm.script_file, "r", encoding="utf-8") as f:
                    self.script_data = json.load(f)
                self.scenes = self.script_data.get("scenes", [])
                logger.info(f"💾 Loaded existing script: {len(self.scenes)} scenes")
                return True
            except Exception as e:
                logger.warning(f"⚠️ Failed to load script: {e}")
        return False

    # ---- Phase 1: Script Generation ----

    async def generate_script(self):
        """Phase 1: Generate the Bible animation script."""
        logger.info("📖 ═══ Phase 1: Script Generation ═══")

        if self._load_existing_script():
            logger.info("⏭️ Script already exists, skipping generation.")
            return

        if not self.book or not self.chapter:
            raise ValueError("Book and chapter are required for script generation.")

        result = await self.script_gen.generate(
            book=self.book,
            chapter=self.chapter,
            target_duration=self.target_duration,
            output_dir=self.pm.root,
            chapter_context=self.chapter_context,
        )

        self.script_data = {
            "plan": result["plan"],
            "scenes": result["scenes"],
        }
        self.scenes = result["scenes"]

        logger.info(f"✅ Script generated: {len(self.scenes)} scenes")
        logger.info(f"📝 Scene prompts: {self.pm.scene_prompts_file}")

    # ---- Phase 1.5: Character Reference Sheets ----

    async def generate_character_sheets(self):
        """
        Phase 1.5: Generate character reference sheets.

        Strategy:
        - ≤3 characters: one sheet per character (individual)
        - >3 characters: 2 individual sheets (top characters)
                        + 1 combined group sheet (all remaining, with names labeled)
        """
        logger.info("🎨 ═══ Phase 1.5: Character Reference Sheets ═══")

        if not self.scenes:
            self._load_existing_script()

        # Collect characters and count scene appearances
        char_freq = {}
        for scene in self.scenes:
            for cid in scene.get("characters", []):
                char_freq[cid] = char_freq.get(cid, 0) + 1

        if not char_freq:
            logger.info("⏭️ No characters found in script, skipping sheet generation.")
            return

        sheets_dir = os.path.join(self.pm.root, "character_sheets")
        os.makedirs(sheets_dir, exist_ok=True)

        # Sort by frequency (most appearances first)
        char_list = sorted(char_freq.keys(), key=lambda c: -char_freq[c])
        logger.info(f"👥 Characters by frequency: {[(c, char_freq[c]) for c in char_list]}")
        generated = 0

        if len(char_list) <= 3:
            # Individual sheets for all
            for cid in char_list:
                ok = await self._generate_single_sheet(cid, sheets_dir, freq=char_freq[cid])
                if ok:
                    generated += 1
        else:
            # Top 2 get individual sheets
            top_chars = char_list[:2]
            remaining_chars = char_list[2:]

            for cid in top_chars:
                ok = await self._generate_single_sheet(cid, sheets_dir, freq=char_freq[cid])
                if ok:
                    generated += 1

            # Remaining all go into one combined group sheet
            ok = await self._generate_group_sheet(remaining_chars, sheets_dir)
            if ok:
                generated += 1

        # Also save JSON metadata with frequency info
        meta_path = os.path.join(sheets_dir, "character_metadata.json")
        metadata = {}
        for rank, cid in enumerate(char_list, 1):
            meta = self.char_db.get_json_metadata(cid) or {}
            meta["scene_appearances"] = char_freq[cid]
            meta["frequency_rank"] = rank
            metadata[cid] = meta
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        logger.info(f"📋 Character JSON metadata → {meta_path}")

        total_sheets = min(len(char_list), 3) if len(char_list) > 3 else len(char_list)
        logger.info(f"✅ Character Sheets Complete: {generated}/{total_sheets} sheets ({len(char_list)} characters)")

    async def _generate_single_sheet(self, cid: str, sheets_dir: str, freq: int = 0) -> bool:
        """Generate an individual character reference sheet."""
        suffix = f"_x{freq}" if freq else ""
        sheet_path = os.path.join(sheets_dir, f"{cid}{suffix}_ref_sheet.png")

        if os.path.exists(sheet_path) and os.path.getsize(sheet_path) > 1024:
            logger.info(f"⏭️ {cid}: Character sheet already exists")
            return True

        prompt = self.char_db.get_character_sheet_prompt(cid)
        if not prompt:
            logger.warning(f"⚠️ {cid}: No character data, skipping sheet")
            return False

        style_desc = self.style.get("style_anchor", "")
        if style_desc:
            prompt += f"\n\nVisual Style: {style_desc}"

        logger.info(f"🎨 {cid}: Generating character reference sheet...")

        try:
            result = await self.ai.generate_image(prompt=prompt, output_path=sheet_path)
            if result:
                logger.info(f"✅ {cid}: Sheet saved → {sheet_path}")
                return True
            else:
                logger.warning(f"⚠️ {cid}: Image generation returned no result")
                return False
        except Exception as e:
            logger.warning(f"⚠️ {cid}: Sheet generation failed: {e}")
            return False

    async def _generate_group_sheet(self, char_ids: list, sheets_dir: str) -> bool:
        """Generate a combined group sheet for multiple characters with names labeled."""
        group_name = "_".join(char_ids[:3])
        if len(char_ids) > 3:
            group_name += f"_and_{len(char_ids)-3}_more"
        sheet_path = os.path.join(sheets_dir, f"GROUP_{group_name}_ref_sheet.png")

        if os.path.exists(sheet_path) and os.path.getsize(sheet_path) > 1024:
            logger.info(f"⏭️ Group sheet already exists: {sheet_path}")
            return True

        # Build combined descriptions
        char_descriptions = []
        for cid in char_ids:
            ch = self.char_db.characters.get(cid)
            if not ch:
                ch = self.char_db.find_by_name(cid)
            if ch:
                name = ch.get("anchor_name", ch.get("name_en", cid))
                desc = ch.get("stream_description", ch.get("appearance", ""))
                clothing = ch.get("clothing", "")
                char_descriptions.append(
                    f"• {name}: {desc}. Clothing: {clothing}"
                )
            else:
                char_descriptions.append(f"• {cid}: Biblical character")

        chars_text = "\n".join(char_descriptions)
        char_names = ", ".join(
            self.char_db.characters.get(cid, {}).get("anchor_name",
                self.char_db.characters.get(cid, {}).get("name_en", cid))
            for cid in char_ids
        )

        style_desc = self.style.get("style_anchor", "")
        style_line = f"\n\nVisual Style: {style_desc}" if style_desc else ""

        prompt = f"""Create a professional CHARACTER GROUP REFERENCE SHEET featuring {len(char_ids)} characters: {char_names}.

CHARACTER DESCRIPTIONS:
{chars_text}

SHEET LAYOUT:
Arrange all {len(char_ids)} characters standing side by side in a single row, each in a relaxed A-pose.
Each character MUST have their NAME clearly labeled BELOW their figure in bold text.
Show full-body front view for each character with consistent scale.
Characters should be evenly spaced with clear visual separation.

LABELING:
- Place each character's name in large, clear, readable text directly below their feet
- Names: {char_names}

CONSISTENCY RULES:
- Clean, neutral plain background
- Maintain perfect identity distinction between each character
- Even, consistent lighting across the entire sheet
- Crisp, print-ready reference with sharp details{style_line}"""

        logger.info(f"🎨 GROUP: Generating combined sheet for {char_names}...")

        try:
            result = await self.ai.generate_image(prompt=prompt, output_path=sheet_path)
            if result:
                logger.info(f"✅ GROUP: Sheet saved → {sheet_path}")
                return True
            else:
                logger.warning(f"⚠️ GROUP: Image generation returned no result")
                return False
        except Exception as e:
            logger.warning(f"⚠️ GROUP: Sheet generation failed: {e}")
            return False

    # ---- Phase 2: TTS Generation ----

    async def generate_tts_assets(self):
        """Phase 2: Generate TTS audio + VTT for all scenes."""
        logger.info("🗣️ ═══ Phase 2: TTS Generation ═══")

        if not self.scenes:
            self._load_existing_script()

        if not self.scenes:
            raise RuntimeError("No scenes found. Run script generation first.")

        total = len(self.scenes)
        success_count = 0

        for scene in self.scenes:
            idx = scene["id"]
            narration = scene.get("narration", "")
            audio_path = self.pm.get_audio_path(idx)
            vtt_path = self.pm.get_vtt_path(idx)

            # Skip if already generated
            if (os.path.exists(audio_path) and os.path.getsize(audio_path) > 1024
                    and os.path.exists(vtt_path) and os.path.getsize(vtt_path) > 10):
                logger.info(f"⏭️ Scene {idx}/{total}: TTS already exists")
                success_count += 1
                continue

            clean_text = preprocess_text_for_tts(narration)
            if not clean_text:
                logger.warning(f"⚠️ Scene {idx}: Empty narration, skipping TTS")
                continue

            logger.info(f"🗣️ Scene {idx}/{total}: Generating TTS...")

            # Determine voice from project language
            language = getattr(self, 'chapter_context', {}).get('language', 'en')
            voice = get_voice_for_language(language)
            success, msg, _ = await generate_tts(clean_text, audio_path, voice=voice)

            if success:
                success_count += 1
                logger.info(f"✅ Scene {idx}: TTS complete")
            else:
                logger.error(f"❌ Scene {idx}: TTS failed - {msg}")

        logger.info(f"✅ TTS Phase Complete: {success_count}/{total} scenes")

    # ---- Phase 3: Wait for User ----

    def print_scene_prompts(self):
        """Print scene prompt file location and summary for the user."""
        logger.info("🎥 ═══ Phase 3: Scene Video Production (YOUR TURN!) ═══")
        logger.info("")
        logger.info("=" * 60)

        # Character reference sheets
        sheets_dir = os.path.join(self.pm.root, "character_sheets")
        if os.path.exists(sheets_dir):
            sheets = [f for f in os.listdir(sheets_dir) if f.endswith(".png")]
            if sheets:
                logger.info(f"🎨 Character reference sheets ({len(sheets)}):")
                for s in sorted(sheets):
                    logger.info(f"   {os.path.join(sheets_dir, s)}")
                logger.info(f"📋 Character JSON metadata:")
                logger.info(f"   {os.path.join(sheets_dir, 'character_metadata.json')}")
                logger.info("")

        logger.info(f"📝 Scene prompts (text):")
        logger.info(f"   {self.pm.scene_prompts_file}")
        json_prompts = os.path.join(self.pm.root, "scene_prompts.json")
        if os.path.exists(json_prompts):
            logger.info(f"📝 Scene prompts (JSON for Veo):")
            logger.info(f"   {json_prompts}")
        logger.info("")
        logger.info(f"📁 Place your scene videos here:")
        logger.info(f"   {self.pm.scenes}")
        logger.info("")
        logger.info(f"📋 Expected files:")

        for scene in self.scenes:
            idx = scene["id"]
            logger.info(f"   scene_{idx:03d}.mp4")

        logger.info("")
        logger.info("=" * 60)
        logger.info("")
        logger.info("After placing all scene videos, resume with:")
        logger.info(f"   ./run_bible.sh --resume {self.run_id}")
        logger.info("")

    def normalize_scene_files(self):
        """
        Auto-detect and rename/copy user-uploaded scene videos to expected format.
        
        Handles various naming patterns:
        - Scene_1_objects_1080p_*.mp4  (Veo download format)
        - scene_1.mp4, scene 1.mp4
        - 1.mp4, 01.mp4, 001.mp4
        - scene_001.mp4 (already correct)
        """
        scenes_dir = self.pm.scenes_shorts if (self.shorts_mode and hasattr(self.pm, 'scenes_shorts')) else self.pm.scenes
        if not os.path.exists(scenes_dir):
            return

        # Patterns to extract scene number from filename
        patterns = [
            r'(?i)P\d+[_\s-]*scene[_\s-]*(\d+)',  # P01_scene_1_1080p, P02_scene_2
            r'(?i)scene[_\s-]*(\d+)',   # Scene_1, scene 1, scene-1, Scene_01
            r'^(\d{1,3})(?:\D|$)',       # 1.mp4, 01.mp4
        ]

        video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
        existing_files = {}  # scene_num -> source file

        for fname in os.listdir(scenes_dir):
            fpath = os.path.join(scenes_dir, fname)
            if not os.path.isfile(fpath):
                continue
            _, ext = os.path.splitext(fname)
            if ext.lower() not in video_exts:
                continue

            # Already in correct format?
            correct_match = re.match(r'^scene_(\d{3})\.(mp4|mov|avi|mkv|webm)$', fname, re.IGNORECASE)
            if correct_match:
                num = int(correct_match.group(1))
                existing_files[num] = fpath
                continue

            # Try to extract scene number
            name_no_ext = os.path.splitext(fname)[0]
            for pattern in patterns:
                m = re.search(pattern, name_no_ext)
                if m:
                    num = int(m.group(1))
                    if num not in existing_files:
                        existing_files[num] = fpath
                    break

        # Copy/rename files to expected format
        renamed_count = 0
        for num, src_path in sorted(existing_files.items()):
            expected_name = f"scene_{num:03d}.mp4"
            expected_path = os.path.join(scenes_dir, expected_name)

            if src_path == expected_path:
                continue  # Already correct

            if os.path.exists(expected_path):
                continue  # Don't overwrite

            logger.info(f"📎 Renaming: {os.path.basename(src_path)} → {expected_name}")
            shutil.copy2(src_path, expected_path)
            renamed_count += 1

        if renamed_count > 0:
            logger.info(f"✅ Normalized {renamed_count} scene files")

    def check_scene_videos(self) -> dict:
        """Check which scene videos have been provided."""
        # Auto-normalize file names first
        self.normalize_scene_files()

        scenes_dir = self.pm.scenes_shorts if (self.shorts_mode and hasattr(self.pm, 'scenes_shorts')) else self.pm.scenes
        result = validate_scene_videos(scenes_dir, len(self.scenes))
        if result["missing"]:
            logger.warning(
                f"⚠️ Missing scene videos: {result['missing']}"
            )
        else:
            logger.info(f"✅ All {len(result['present'])} scene videos present!")
        return result

    # ---- Phase 4: Render ----

    def render_scene(self, scene_id: int) -> bool:
        """Render a single scene: scene video + TTS audio + VTT subtitles.
        If the scene has skip_tts=True (dialogue-heavy), renders video-only
        without TTS audio overlay and without subtitle burn-in.
        Supports shorts_mode (9:16, 1080x1920) when self.shorts_mode is True.
        """
        shorts = self.shorts_mode
        video_path = self.pm.get_scene_video_path(scene_id, shorts=shorts) if hasattr(self.pm, 'scenes_shorts') else self.pm.get_scene_video_path(scene_id)
        audio_path = self.pm.get_audio_path(scene_id)
        vtt_path = self.pm.get_vtt_path(scene_id)
        output_path = self.pm.get_clip_path(scene_id, shorts=shorts) if hasattr(self.pm, 'clips_shorts') else self.pm.get_clip_path(scene_id)

        # Skip if already rendered
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024 * 1024:
            logger.info(f"⏭️ Scene {scene_id}: Already rendered")
            return True

        if not os.path.exists(video_path):
            logger.error(f"❌ Scene {scene_id}: Video not found: {video_path}")
            return False

        # Determine audio priority for this scene
        # audio_priority: "tts" (default) | "veo" (use Veo audio) | "mix" (blend both)
        scene_data = None
        for s in self.scenes:
            if s.get("id") == scene_id:
                scene_data = s
                break

        audio_priority = "tts"
        if scene_data:
            audio_priority = scene_data.get("audio_priority", "tts")
            # Backward compat: skip_tts=True → audio_priority="veo"
            if audio_priority == "tts" and scene_data.get("skip_tts", False):
                audio_priority = "veo"

        if audio_priority == "veo":
            # ---- Veo audio: preserve native audio, still burn VTT subtitles ----
            logger.info(
                f"🎬 Scene {scene_id}: Rendering with VEO AUDIO + VTT subtitles"
            )
            video_duration = get_duration(video_path)
            fps = 24
            target_w, target_h = (1080, 1920) if self.shorts_mode else (1920, 1080)

            filter_complex = (
                f"[0:v]"
                f"fps={fps},setpts=N/({fps}*TB),"
                f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
                f"crop={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
                f"fps={fps},setpts=N/({fps}*TB)[v]"
            )

            # Step 1: Base render with Veo audio
            temp_path = output_path.replace(".mp4", "_temp.mp4")
            cmd = [
                "ffmpeg", "-y", "-nostdin",
                "-i", video_path,
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-r", str(fps), "-fps_mode", "cfr",
                "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                temp_path
            ]

            if not run_cmd(cmd):
                logger.error(f"❌ Scene {scene_id}: Veo-audio render failed")
                return False

            # Step 2: Burn in VTT subtitles
            if os.path.exists(vtt_path) and os.path.getsize(vtt_path) > 10:
                vtt_abs = (os.path.abspath(vtt_path)
                           .replace("\\", "\\\\")
                           .replace(":", "\\:")
                           .replace("'", "'\\\\\'"))
                style = (
                    "Fontname=Arial,FontSize=14,"
                    "PrimaryColour=&H80FFFFFF,OutlineColour=&H80000000,"
                    "BorderStyle=1,Outline=1,Shadow=0,"
                    "Alignment=2,MarginV=20"
                )
                cmd_sub = [
                    "ffmpeg", "-y", "-nostdin",
                    "-i", temp_path,
                    "-vf", f"subtitles='{vtt_abs}':force_style='{style}'",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-c:a", "copy",
                    output_path
                ]
                success = run_cmd(cmd_sub)
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                if not success:
                    logger.error(f"❌ Scene {scene_id}: Veo subtitle burn-in failed")
                    return False
            else:
                if os.path.exists(temp_path):
                    os.rename(temp_path, output_path)

            logger.info(f"✅ Scene {scene_id}: Rendered (veo audio + subtitles)")
            return True

        if audio_priority == "mix":
            # ---- Mix mode: blend Veo audio (80%) + TTS narration (20%) ----
            if not os.path.exists(audio_path):
                logger.warning(
                    f"⚠️ Scene {scene_id}: TTS not found for mix, falling back to veo"
                )
                # Fall through to veo-only path above won't work, render inline
                audio_priority = "veo"
            else:
                logger.info(
                    f"🎬 Scene {scene_id}: Rendering MIXED AUDIO "
                    f"(veo 80% + tts 20%)"
                )
                video_duration = get_duration(video_path)
                audio_duration = get_duration(audio_path)
                fps = 24
                target_w, target_h = (1080, 1920) if self.shorts_mode else (1920, 1080)

                filter_complex = (
                    f"[0:v]fps={fps},setpts=N/({fps}*TB),"
                    f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
                    f"crop={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
                    f"fps={fps},setpts=N/({fps}*TB)[v];"
                    f"[0:a]volume=0.8[veo_a];"
                    f"[1:a]volume=0.2[tts_a];"
                    f"[veo_a][tts_a]amix=inputs=2:duration=longest[a]"
                )

                temp_path = output_path.replace(".mp4", "_temp.mp4")
                cmd = [
                    "ffmpeg", "-y", "-nostdin",
                    "-i", video_path,
                    "-i", audio_path,
                    "-filter_complex", filter_complex,
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-r", str(fps), "-fps_mode", "cfr",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    "-pix_fmt", "yuv420p",
                    temp_path
                ]

                if not run_cmd(cmd):
                    logger.error(f"❌ Scene {scene_id}: Mix render failed")
                    return False

                # Subtitle burn-in
                if os.path.exists(vtt_path) and os.path.getsize(vtt_path) > 10:
                    vtt_abs = (os.path.abspath(vtt_path)
                               .replace("\\", "\\\\")
                               .replace(":", "\\:")
                               .replace("'", "'\\\\\'"))
                    style = (
                        "Fontname=Arial,FontSize=14,"
                        "PrimaryColour=&H80FFFFFF,OutlineColour=&H80000000,"
                        "BorderStyle=1,Outline=1,Shadow=0,"
                        "Alignment=2,MarginV=20"
                    )
                    cmd_sub = [
                        "ffmpeg", "-y", "-nostdin",
                        "-i", temp_path,
                        "-vf", f"subtitles='{vtt_abs}':force_style='{style}'",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                        "-c:a", "copy",
                        output_path
                    ]
                    success = run_cmd(cmd_sub)
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    if not success:
                        logger.error(
                            f"❌ Scene {scene_id}: Mix subtitle burn-in failed"
                        )
                        return False
                else:
                    if os.path.exists(temp_path):
                        os.rename(temp_path, output_path)

                logger.info(f"✅ Scene {scene_id}: Rendered (mixed audio)")
                return True

        # ---- Default TTS mode: render with TTS audio + VTT subtitles ----
        if not os.path.exists(audio_path):
            logger.error(f"❌ Scene {scene_id}: Audio not found: {audio_path}")
            return False

        # Get audio duration
        audio_duration = get_duration(audio_path)
        video_duration = get_duration(video_path)

        if audio_duration <= 0:
            logger.error(f"❌ Scene {scene_id}: Invalid audio duration")
            return False

        logger.info(
            f"🎬 Scene {scene_id}: Rendering "
            f"(video={video_duration:.1f}s, audio={audio_duration:.1f}s)"
        )

        # Config
        fps = 24
        target_w, target_h = (1080, 1920) if self.shorts_mode else (1920, 1080)

        # Handle speed adjustment if video is shorter than audio
        audio_filter = ""
        audio_map = "1:a"
        duration_to_use = audio_duration

        if video_duration > 0 and video_duration < audio_duration:
            speed = audio_duration / video_duration
            if speed > 1.05:
                audio_filter = f"[1:a]atempo={speed}[a_adj];"
                audio_map = "[a_adj]"
                duration_to_use = video_duration
                logger.info(f"⚡ Adjusting audio speed: {speed:.2f}x")

        # Video filter
        filter_complex = (
            f"{audio_filter}[0:v]"
            f"fps={fps},setpts=N/({fps}*TB),"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps},setpts=N/({fps}*TB)[v]"
        )

        temp_path = output_path.replace(".mp4", "_temp.mp4")

        # Base render
        cmd_base = [
            "ffmpeg", "-y", "-nostdin",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", audio_map,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-r", str(fps), "-fps_mode", "cfr",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(duration_to_use),
            "-shortest",
            "-pix_fmt", "yuv420p",
            temp_path
        ]

        if not run_cmd(cmd_base):
            logger.error(f"❌ Scene {scene_id}: Base render failed")
            return False

        # Subtitle burn-in
        if os.path.exists(vtt_path) and os.path.getsize(vtt_path) > 10:
            vtt_abs = (os.path.abspath(vtt_path)
                       .replace("\\", "\\\\")
                       .replace(":", "\\:")
                       .replace("'", "'\\\\'"))

            style = (
                "Fontname=Arial,FontSize=14,"
                "PrimaryColour=&H80FFFFFF,OutlineColour=&H80000000,"
                "BorderStyle=1,Outline=1,Shadow=0,"
                "Alignment=2,MarginV=20"
            )

            cmd_subtitle = [
                "ffmpeg", "-y", "-nostdin",
                "-i", temp_path,
                "-vf", f"subtitles='{vtt_abs}':force_style='{style}'",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "copy",
                output_path
            ]

            success = run_cmd(cmd_subtitle)
            if os.path.exists(temp_path):
                os.remove(temp_path)

            if not success:
                logger.error(f"❌ Scene {scene_id}: Subtitle burn-in failed")
                return False
        else:
            # No subtitles, just rename
            if os.path.exists(temp_path):
                os.rename(temp_path, output_path)

        logger.info(f"✅ Scene {scene_id}: Rendered successfully")
        return True

    async def render_all(self):
        """Phase 4: Render all scenes."""
        mode_label = "SHORTS 9:16" if self.shorts_mode else "16:9"
        logger.info(f"🎬 ═══ Phase 4: Rendering ({mode_label}) ═══")

        if not self.scenes:
            self._load_existing_script()

        # Check all scene videos are present
        check = self.check_scene_videos()
        if check["missing"]:
            logger.error(
                f"❌ Cannot render: {len(check['missing'])} scene videos missing"
            )
            logger.error(f"   Missing: {check['missing']}")
            return False

        total = len(self.scenes)
        success = 0

        for scene in self.scenes:
            if self.render_scene(scene["id"]):
                success += 1

        logger.info(f"✅ Rendering complete: {success}/{total} clips")
        return success == total

    # ---- Intro Auto-Assembly ----

    async def assemble_intro(self, proj):
        """Auto-assemble ch00 intro by extracting scene videos from existing chapters.
        
        Priority order:
        1. Manual map (intro_manual_map.json) - PD-curated overrides
        2. Auto-match from ch01-ch11 (ch12 Outro excluded to avoid CTA content)
        
        After running this, use --resume-chapter to render + merge.
        """
        logger.info("🎬 ═══ Intro Auto-Assembly ═══")
        
        if not self.script_data:
            self._load_existing_script()
        
        intro_scenes = self.script_data.get("scenes", [])
        if not intro_scenes:
            logger.error("❌ No scenes in ch00 script.json")
            return False
        
        # --- Check for manual map (PD-curated overrides) ---
        manual_map_path = os.path.join(self.pm.root, "intro_manual_map.json")
        manual_map = {}
        if os.path.exists(manual_map_path):
            with open(manual_map_path, "r", encoding="utf-8") as f:
                manual_entries = json.load(f)
            for entry in manual_entries:
                manual_map[entry["intro_scene"]] = entry
            logger.info(f"📋 Manual map loaded: {len(manual_map)} entries from intro_manual_map.json")
        
        # --- Build source scene catalog (exclude ch12 Outro to avoid CTA content) ---
        EXCLUDED_CHAPTERS = {12}  # Outro contains CTA/subscribe content
        logger.info("📚 Building source scene catalog from ch01-ch11...")
        source_catalog = []
        chapter_pms = {}  # cache path managers by chapter index
        
        for ch in proj.get_all_chapters():
            idx = ch["index"]
            if idx == 0 or idx in EXCLUDED_CHAPTERS:
                continue
            
            ch_pm = proj.get_chapter_pm(idx)
            if not ch_pm:
                continue
            chapter_pms[idx] = ch_pm
            
            script_path = ch_pm.script_file
            if not os.path.exists(script_path):
                continue
            
            with open(script_path, "r", encoding="utf-8") as f:
                ch_script = json.load(f)
            
            for scene in ch_script.get("scenes", []):
                scene_video = ch_pm.get_scene_video_path(scene["id"])
                if not os.path.exists(scene_video):
                    continue
                
                source_catalog.append({
                    "chapter_idx": idx,
                    "chapter_slug": ch.get("slug", ""),
                    "chapter_title": ch.get("title", ""),
                    "scene_id": scene["id"],
                    "narration": scene.get("narration", ""),
                    "characters": scene.get("characters", []),
                    "video_prompt": scene.get("video_prompt", {}),
                    "path_manager": ch_pm,
                })
        
        active_chapters = len(set(s['chapter_idx'] for s in source_catalog))
        logger.info(f"   Found {len(source_catalog)} source scenes across {active_chapters} chapters (ch12 excluded)")
        
        # --- Assemble: manual map first, then auto-match fallback ---
        os.makedirs(self.pm.scenes, exist_ok=True)
        mapping = []
        used_sources = set()
        
        for intro_scene in intro_scenes:
            intro_id = intro_scene["id"]
            intro_narration = intro_scene.get("narration", "")
            
            # Priority 1: Manual map
            if intro_id in manual_map:
                entry = manual_map[intro_id]
                src_ch = entry["source_chapter"]
                src_sid = entry["source_scene"]
                reason = entry.get("reason", "manual override")
                
                # Get the path manager for this chapter
                ch_pm = chapter_pms.get(src_ch) or proj.get_chapter_pm(src_ch)
                if ch_pm:
                    src_video = ch_pm.get_scene_video_path(src_sid)
                    if os.path.exists(src_video):
                        dst_video = self.pm.get_scene_video_path(intro_id)
                        shutil.copy2(src_video, dst_video)
                        used_sources.add((src_ch, src_sid))
                        
                        mapping.append({
                            "intro_scene": intro_id,
                            "intro_narration": intro_narration[:80],
                            "source_chapter": src_ch,
                            "source_scene": src_sid,
                            "reason": reason,
                            "method": "manual",
                        })
                        
                        logger.info(
                            f"   📌 Intro scene {intro_id:2d} → ch{src_ch:02d} scene {src_sid:2d} "
                            f"(manual: {reason})"
                        )
                        continue
                    else:
                        logger.warning(f"   ⚠️ Manual map scene ch{src_ch:02d} s{src_sid} video not found, falling back to auto")
            
            # Priority 2: Auto-match (fallback)
            intro_chars = intro_scene.get("characters", [])
            intro_prompt = intro_scene.get("video_prompt", {})
            
            best_score = -1
            best_source = None
            
            for src in source_catalog:
                src_key = (src["chapter_idx"], src["scene_id"])
                reuse_penalty = 0.3 if src_key in used_sources else 0.0
                
                score = self._scene_match_score(
                    intro_narration, intro_chars, intro_prompt,
                    src["narration"], src["characters"], src["video_prompt"]
                ) - reuse_penalty
                
                if score > best_score:
                    best_score = score
                    best_source = src
            
            if best_source:
                src_key = (best_source["chapter_idx"], best_source["scene_id"])
                used_sources.add(src_key)
                
                src_video = best_source["path_manager"].get_scene_video_path(best_source["scene_id"])
                dst_video = self.pm.get_scene_video_path(intro_id)
                shutil.copy2(src_video, dst_video)
                
                mapping.append({
                    "intro_scene": intro_id,
                    "intro_narration": intro_narration[:80],
                    "source_chapter": best_source["chapter_idx"],
                    "source_chapter_title": best_source["chapter_title"],
                    "source_scene": best_source["scene_id"],
                    "source_narration": best_source["narration"][:80],
                    "score": round(best_score, 3),
                    "method": "auto",
                })
                
                logger.info(
                    f"   🔄 Intro scene {intro_id:2d} → ch{best_source['chapter_idx']:02d} scene {best_source['scene_id']:2d} "
                    f"(auto, score: {best_score:.3f})"
                )
            else:
                logger.warning(f"   ⚠️ Intro scene {intro_id}: No match found!")
        
        # Save mapping for reference
        mapping_path = os.path.join(self.pm.root, "intro_assembly_map.json")
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        
        # Summary
        manual_count = sum(1 for m in mapping if m.get("method") == "manual")
        auto_count = sum(1 for m in mapping if m.get("method") == "auto")
        logger.info(f"\n📊 Assembly Summary:")
        logger.info(f"   Total intro scenes: {len(intro_scenes)}")
        logger.info(f"   Manual (PD-curated): {manual_count}")
        logger.info(f"   Auto-matched: {auto_count}")
        logger.info(f"   Mapping saved: {mapping_path}")
        logger.info(f"\n▶️ Next: render the intro chapter:")
        logger.info(f"   python -m api.production.orchestrator --project {proj.pm.slug} --chapter 0 --resume-chapter")
        
        return True
    
    @staticmethod
    def _scene_match_score(
        intro_narr: str, intro_chars: list, intro_prompt: dict,
        src_narr: str, src_chars: list, src_prompt: dict
    ) -> float:
        """Score how well a source scene matches an intro scene.
        
        Components:
        1. Narration text similarity (SequenceMatcher)
        2. Character overlap
        3. Keyword overlap from video prompt fields
        """
        score = 0.0
        
        # 1. Narration text similarity (weight: 0.4)
        intro_lower = intro_narr.lower()
        src_lower = src_narr.lower()
        text_sim = SequenceMatcher(None, intro_lower, src_lower).ratio()
        score += text_sim * 0.4
        
        # 2. Character overlap (weight: 0.25)
        intro_char_set = {c.lower() for c in intro_chars}
        src_char_set = {c.lower() for c in src_chars}
        if intro_char_set and src_char_set:
            overlap = len(intro_char_set & src_char_set)
            total = len(intro_char_set | src_char_set)
            char_sim = overlap / total if total > 0 else 0
            score += char_sim * 0.25
        elif not intro_char_set and not src_char_set:
            # Both scenery-only — slight bonus
            score += 0.1
        
        # 3. Keyword overlap from video prompt (weight: 0.35)
        intro_keywords = _extract_keywords(intro_prompt, intro_narr)
        src_keywords = _extract_keywords(src_prompt, src_narr)
        if intro_keywords and src_keywords:
            overlap = len(intro_keywords & src_keywords)
            total = len(intro_keywords | src_keywords)
            kw_sim = overlap / total if total > 0 else 0
            score += kw_sim * 0.35
        
        return score

    # ---- Phase 5: Merge ----

    def merge_clips(self) -> Optional[str]:
        """Phase 5: Merge all rendered clips into master video."""
        logger.info("📥 ═══ Phase 5: Merging ═══")

        shorts = self.shorts_mode
        render_dir = self.pm.clips_shorts if (shorts and hasattr(self.pm, 'clips_shorts')) else self.pm.rendered
        concat_list = os.path.join(render_dir, "concat_list.txt")

        # Build concat list from existing clips
        clip_ids = []
        for scene in self.scenes:
            clip_path = self.pm.get_clip_path(scene["id"], shorts=shorts) if hasattr(self.pm, 'clips_shorts') else self.pm.get_clip_path(scene["id"])
            if os.path.exists(clip_path) and os.path.getsize(clip_path) > 1024:
                clip_ids.append(scene["id"])

        if not clip_ids:
            logger.error("❌ No clips to merge!")
            return None

        # Pre-normalize all clips to 48kHz stereo to prevent
        # concat audio corruption from mixed formats (TTS=24kHz mono, Veo=48kHz stereo)
        norm_dir = os.path.join(render_dir, "_normalized")
        os.makedirs(norm_dir, exist_ok=True)

        logger.info("🔧 Pre-normalizing audio to 48kHz stereo...")
        for idx in sorted(clip_ids):
            src = self.pm.get_clip_path(idx, shorts=shorts) if hasattr(self.pm, 'clips_shorts') else self.pm.get_clip_path(idx)
            dst = os.path.join(norm_dir, f"clip_{idx:03d}.mp4")
            norm_cmd = [
                "ffmpeg", "-y", "-nostdin",
                "-i", src,
                "-c:v", "copy",
                "-af", "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo",
                "-c:a", "aac", "-b:a", "192k",
                dst
            ]
            if not run_cmd(norm_cmd):
                logger.error(f"❌ Audio normalization failed for clip {idx}")
                return None

        # Write concat list pointing to normalized clips
        norm_concat = os.path.join(norm_dir, "concat_list.txt")
        with open(norm_concat, "w") as f:
            for idx in sorted(clip_ids):
                f.write(f"file 'clip_{idx:03d}.mp4'\n")

        output = self.pm.chapter_shorts_video if (shorts and hasattr(self.pm, 'chapter_shorts_video')) else self.pm.final_video

        merge_cmd = (
            f"ffmpeg -y -f concat -safe 0 -i {norm_concat} "
            f"-c copy {output}"
        )

        if run_cmd(merge_cmd):
            # Clean up normalized temp files
            shutil.rmtree(norm_dir, ignore_errors=True)
            duration = get_duration(output)
            logger.info(f"✅ Master video created: {output} ({duration:.1f}s)")

            # Apply Universal Veo CTA (Shorts + Intro ch00)
            if shorts or (hasattr(self.pm, 'chapter_idx') and self.pm.chapter_idx == 0):
                output = self._apply_universal_cta(output, is_shorts=shorts)

            return output
        else:
            logger.error("❌ Merge failed!")
            return None

    def _apply_universal_cta(self, video_path: str, is_shorts: bool = False) -> str:
        """Apply universal Veo CTA overlay (Green Screen) to video."""
        # Standard Veo CTA asset
        cta_path = os.path.join("data", "assets", "cta", "veo_cta.mp4")
        if not os.path.exists(cta_path):
            logger.warning(f"⚠️ Veo CTA not found at {cta_path}. Skipping.")
            return video_path

        logger.info(f"✨ Applying Veo CTA ({'Shorts' if is_shorts else 'Intro'})...")
        try:
            duration = get_duration(video_path)
            # CTA logic: Overlay at the end (last 5s)
            start_time = max(0, duration - 5.0)
            output_path = video_path.replace(".mp4", "_cta.mp4")

            # Shorts (1080w): scale to 860px (~80%)
            # Intro (1920w): scale to 640px (~33%)
            scale_w = 860 if is_shorts else 640
            
            # Position Y: 
            # Shorts: H-h-550 (raise for captions + UI space)
            # Intro: H-h-140 (Approved: Just above subtitles)
            y_pos = "H-h-550" if is_shorts else "H-h-140"

            cmd = [
                "ffmpeg", "-y", "-nostdin",
                "-i", video_path,
                "-stream_loop", "-1", "-i", cta_path,  # Loop CTA to ensure full 5s coverage
                "-filter_complex",
                # 1. Scale CTA explicitly
                f"[1:v]scale={scale_w}:-1[cta_sized];"
                # 2. Key out Green (0x00FF00) - Approved: Sim 0.33, Blend 0.0
                f"[cta_sized]chromakey=0x00FF00:0.33:0.0[cta_keyed];"
                # 3. Shift CTA timestamp to start_time
                f"[cta_keyed]setpts=PTS-STARTPTS+{start_time}/TB[cta_final];"
                # 4. Overlay on Main Video
                f"[0:v][cta_final]overlay=(W-w)/2:{y_pos}:enable='between(t,{start_time},{duration})':shortest=1",
                "-c:a", "copy",
                "-shortest",
                output_path
            ]
            
            if run_cmd(cmd):
                shutil.move(output_path, video_path)
                logger.info("✅ Universal CTA overlay applied.")
                return video_path
            else:
                logger.error("❌ Failed to apply Universal CTA overlay")
                if os.path.exists(output_path):
                    os.remove(output_path)
                return video_path
        except Exception as e:
            logger.error(f"❌ Error applying Universal CTA: {e}")
            return video_path

    # ---- Phase 6: Metadata ----

    async def generate_metadata(self):
        """Phase 6: Generate YouTube metadata."""
        logger.info("📦 ═══ Phase 6: YouTube Metadata ═══")

        if not self.script_data:
            self._load_existing_script()

        plan = self.script_data.get("plan", {})
        metadata = await self.ai.generate_metadata(self.script_data, plan)

        metadata_path = os.path.join(self.pm.final, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Metadata saved: {metadata_path}")

        # Print metadata summary
        titles = metadata.get("titles", [])
        if titles:
            logger.info(f"📌 Suggested titles:")
            for i, t in enumerate(titles, 1):
                logger.info(f"   {i}. {t}")

        return metadata

    # ---- Main Execution ----

    async def run(self, mode: str = "full"):
        """
        Main execution pipeline.
        
        Modes:
        - "full": Run all phases (stops after Phase 3 for user input)
        - "script-only": Only generate script
        - "resume": Skip script/TTS, render + merge (user has added videos)
        """
        logger.info(f"🎹 BibleOrchestrator Starting. Mode: {mode}, Run ID: {self.run_id}")
        start_time = time.time()

        try:
            if mode == "script-only":
                await self.generate_script()
                self.print_scene_prompts()

            elif mode == "resume":
                # Load existing script
                if not self._load_existing_script():
                    logger.error("❌ No script found to resume. Run generation first.")
                    return

                # Check for missing TTS and generate if needed
                await self.generate_tts_assets()

                # Render + Merge
                render_ok = await self.render_all()
                if render_ok:
                    output = self.merge_clips()
                    if output:
                        await self.generate_metadata()
                        elapsed = time.time() - start_time
                        logger.info(f"✨ Production complete in {elapsed:.0f}s!")
                        logger.info(f"🎬 Final video: {output}")

            else:  # "full"
                # Phase 1: Script
                await self.generate_script()

                # Phase 1.5: Character Reference Sheets
                await self.generate_character_sheets()

                # Phase 2: TTS
                await self.generate_tts_assets()

                # Phase 3: Pause for user
                self.print_scene_prompts()

                elapsed = time.time() - start_time
                logger.info(f"⏱️ Preparation complete in {elapsed:.0f}s")
                logger.info("🛑 Pausing for scene video production.")
                logger.info(
                    f"   Resume with: ./run_bible.sh --resume {self.run_id}"
                )

        except Exception as e:
            logger.error(f"❌ Pipeline error: {e}")
            import traceback
            traceback.print_exc()
            raise

# ---- Intro Assembly Helpers ----

def _extract_keywords(prompt: dict, narration: str) -> set:
    """Extract meaningful keywords from a video prompt and narration."""
    text_parts = [
        narration,
        prompt.get("objects", ""),
        prompt.get("action", ""),
        prompt.get("atmosphere", ""),
    ]
    full_text = " ".join(text_parts).lower()

    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "and", "or", "but", "not", "no", "nor", "so", "yet",
        "as", "if", "then", "than", "that", "this", "these", "those",
        "his", "her", "its", "their", "your", "our", "my",
        "he", "she", "it", "they", "we", "you", "i",
        "him", "them", "us", "me", "who", "whom", "which",
        "what", "where", "when", "how", "why",
        "all", "each", "every", "both", "few", "more",
        "other", "some", "such", "only", "own", "same",
        "up", "out", "off", "over", "under", "into",
        "about", "between", "through", "during", "before", "after",
        "pixar", "disney", "3d", "animation", "rendered", "style",
        "quality", "detailed", "ultra", "4k", "cinematic",
        "shot", "medium", "close", "wide", "angle", "camera",
    }

    words = re.findall(r'[a-z]+', full_text)
    return {w for w in words if len(w) > 2 and w not in stop_words}

# ---- YouTube Metadata Generator ----

async def generate_project_metadata(project_slug: str):
    """
    Generate comprehensive YouTube metadata for the entire project:
    1. Project-level (full video): 3 titles, 3 thumbnail prompts, description, hashtags
    2. Introduction (ch00): 3 titles, 3 thumbnail prompts, description, hashtags
    3. Per-chapter shorts: title, thumbnail prompt, description, hashtags
    """
    from api.services.ai import AIClient
    from google.genai import types

    proj = ProjectManager(project_slug)
    ai = AIClient()
    chapters = proj.get_all_chapters()
    project_data = proj.project_data

    # Gather all chapter summaries for context
    chapter_summaries = []
    for ch in chapters:
        cpm = proj.get_chapter_pm(ch["index"])
        script_path = cpm.script_file
        summary = ""
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            narrations = [s.get("narration", "") for s in script.get("scenes", [])]
            summary = " ".join(narrations)[:500]
        chapter_summaries.append({
            "index": ch["index"],
            "title": ch["title"],
            "key_events": ch.get("key_events", ""),
            "summary_excerpt": summary,
        })

    language = project_data.get("language", "en")
    lang_instruction = "한국어로" if language == "ko" else "in English"
    project_title = project_data.get("title", project_slug)
    scripture_ref = project_data.get("scripture_ref", "")

    # ---- 1. Project-level metadata ----
    logger.info("📦 Generating project-level YouTube metadata...")

    project_prompt = f"""
    Generate YouTube metadata {lang_instruction} for a full-length Bible animation video.

    Project: {project_title}
    Scripture: {scripture_ref}
    Total chapters: {len(chapters)}
    Chapter list: {json.dumps([{{"title": c["title"], "key_events": c.get("key_events","")}} for c in chapters], ensure_ascii=False)}

    === YouTube SEO Best Practices ===
    TITLE RULES:
    - Use action/journey phrasing: "From Shepherd to King", "Rise of...", NOT static labels
    - Include format hint: "Full Movie", "3D Animated", "Stunning"
    - Keep under 70 characters
    - Put the most searchable keyword first (e.g., "David and Goliath")

    DESCRIPTION RULES:
    - Start with subtitle line: "Full Movie | 3D Animated Bible Story | [Journey phrase] | Bible Stories for Kids and Adults"
    - ALWAYS include "Bible Stories for Kids and Adults" for search breadth
    - Include a hook paragraph (2-3 sentences, emotional, what the viewer will experience)
    - Include "🎬 WHAT YOU'LL DISCOVER IN THIS MOVIE:" section
    - Include chapter timestamps section with 📖 CHAPTERS header
    - Include "✝️ KEY BIBLE VERSES" section with 2-3 actual verses and references
    - Include "📚 SCRIPTURE REFERENCE" section
    - End with CTA: "If this video blessed you, please LIKE 👍, COMMENT 💬, and SUBSCRIBE 🔔"

    HASHTAG RULES:
    - Only include hashtags DIRECTLY relevant to the actual story content
    - DO NOT include character names or themes that don't appear in the story
      (e.g., do NOT add #Jesus if Jesus doesn't appear in the story)
    - Include format tags: #3danimation, #animatedbiblemovie, #christiananimation
    - Include audience tags: #biblestoriesforkids, #sundayschool
    - Include trending variations: #davidvsgoliath, #faithoverfear
    - Include channel-style tags: #bibleanimation, #biblemovies
    - 15-25 hashtags total, all lowercase

    TAGS (separate from hashtags — used for YouTube internal search):
    - Include both short and long-tail keywords
    - Include "Bible Stories for Kids", "Bible Stories for Adults", "Full Movie"

    Return JSON with this EXACT structure:
    {{
      "title": "Main title (best one, action/journey phrasing)",
      "alt_titles": ["Alternative title 1", "Alternative title 2", "Alternative title 3"],
      "description_header": "Subtitle line for description",
      "description_hook": "2-3 sentence emotional hook paragraph",
      "what_youll_discover": "🎬 WHAT YOU'LL DISCOVER IN THIS MOVIE:\\n[detailed paragraph about key story moments]",
      "chapters_section": "📖 CHAPTERS\\n00:00 Introduction\\n...",
      "key_bible_verses": [{{"verse": "...", "reference": "Book Chapter:Verse"}}],
      "scripture_reference": "📚 SCRIPTURE REFERENCE\\n[description]",
      "cta": "CTA text with emojis",
      "hashtags": ["#hashtag1", "#hashtag2"],
      "tags": ["keyword1", "keyword2"]
    }}
    """

    project_meta = await _call_ai_for_metadata(ai, project_prompt)

    # Save project-level metadata
    project_meta_path = os.path.join(proj.pm.final_dir, "metadata.json")
    os.makedirs(proj.pm.final_dir, exist_ok=True)
    with open(project_meta_path, "w", encoding="utf-8") as f:
        json.dump(project_meta, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Project metadata saved: {project_meta_path}")

    # ---- 2. Introduction (ch00) metadata ----
    logger.info("📦 Generating introduction metadata...")

    intro_ch = next((c for c in chapters if c["index"] == 0), None)
    intro_meta = {}
    if intro_ch:
        intro_prompt = f"""
        Generate YouTube metadata {lang_instruction} for a Bible animation TRAILER/INTRODUCTION video.
        This is a short preview of the full story to hook new viewers.

        Project: {project_title}
        Scripture: {scripture_ref}
        Full story chapters: {json.dumps([c["title"] for c in chapters if c["index"] > 0], ensure_ascii=False)}

        Return JSON:
        {{
          "titles": [
            "Trailer title 1 (curiosity-driven, teaser style)",
            "Trailer title 2 (emotional hook)",
            "Trailer title 3 (action-focused)"
          ],
          "thumbnail_prompts": [
            "Dramatic thumbnail prompt 1 (highlight the most exciting visual moment)",
            "Thumbnail prompt 2 (character-focused, emotional)",
            "Thumbnail prompt 3 (epic wide shot, cinematic)"
          ],
          "description": "YouTube description for trailer (300-500 chars, link to full video, CTA)",
          "hashtags": ["#hashtag1", "#hashtag2", "..."],
          "tags": ["keyword1", "keyword2", "..."]
        }}
        """
        intro_meta = await _call_ai_for_metadata(ai, intro_prompt)

        intro_cpm = proj.get_chapter_pm(0)
        intro_meta_path = os.path.join(intro_cpm.root, "metadata.json")
        with open(intro_meta_path, "w", encoding="utf-8") as f:
            json.dump(intro_meta, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Introduction metadata saved: {intro_meta_path}")

    # ---- 3. Per-chapter shorts metadata ----
    logger.info("📦 Generating per-chapter shorts metadata...")

    all_shorts_meta = {}
    for ch_info in chapter_summaries:
        if ch_info["index"] == 0:
            continue  # intro handled separately

        ch_title = ch_info["title"]
        ch_events = ch_info["key_events"]
        ch_excerpt = ch_info["summary_excerpt"]

        shorts_prompt = f"""
        Generate YouTube Shorts metadata {lang_instruction} for a 9:16 vertical short video.
        This is a Shorts version of one chapter from a Bible animation series.

        Series: {project_title}
        Chapter {ch_info["index"]}: {ch_title}
        Key events: {ch_events}
        Script excerpt: {ch_excerpt}

        Important: Shorts titles must be SHORT (under 40 chars), punchy, and hook-driven.

        Return JSON:
        {{
          "title": "Short punchy Shorts title (under 40 chars)",
          "thumbnail_prompt": "Vertical 9:16 thumbnail prompt (dramatic moment, bold, mobile-optimized)",
          "description": "Short Shorts description (100-200 chars, include series link)",
          "hashtags": ["#Shorts", "#hashtag1", "#hashtag2", "..."]
        }}
        """

        ch_meta = await _call_ai_for_metadata(ai, shorts_prompt)
        all_shorts_meta[f"ch{ch_info['index']:02d}"] = ch_meta

        # Save per-chapter
        ch_obj = proj.get_chapter(ch_info["index"])
        if ch_obj:
            cpm = proj.get_chapter_pm(ch_info["index"])
            shorts_meta_path = os.path.join(cpm.root, "shorts_metadata.json")
            with open(shorts_meta_path, "w", encoding="utf-8") as f:
                json.dump(ch_meta, f, ensure_ascii=False, indent=2)

        logger.info(f"   ✅ Ch{ch_info['index']:02d}: {ch_meta.get('title', ch_title)}")

    # ---- Save combined summary ----
    combined = {
        "project": project_meta,
        "introduction": intro_meta,
        "shorts": all_shorts_meta,
    }
    combined_path = os.path.join(proj.pm.root, "youtube_metadata.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    logger.info(f"\n✅ All YouTube metadata saved!")
    logger.info(f"   Combined: {combined_path}")
    logger.info(f"   Project:  {project_meta_path}")
    if intro_meta:
        logger.info(f"   Intro:    {intro_meta_path}")
    logger.info(f"   Shorts:   {len(all_shorts_meta)} chapters")

    # Print summary
    logger.info("\n📋 === Metadata Summary ===")
    if project_meta.get("title"):
        logger.info(f"🎬 Project title: {project_meta['title']}")
        for i, t in enumerate(project_meta.get("alt_titles", []), 1):
            logger.info(f"   Alt {i}. {t}")
    if intro_meta.get("title"):
        logger.info(f"🎥 Introduction title: {intro_meta['title']}")
        for i, t in enumerate(intro_meta.get("alt_titles", []), 1):
            logger.info(f"   Alt {i}. {t}")
    logger.info(f"📱 Shorts: {len(all_shorts_meta)} chapters generated")

    return combined


async def _call_ai_for_metadata(ai, prompt: str) -> dict:
    """Call Gemini AI for metadata generation with JSON response."""
    from google.genai import types
    import asyncio

    config = types.GenerateContentConfig(
        temperature=0.8,
        response_mime_type="application/json",
    )

    try:
        async def _call():
            return await asyncio.to_thread(
                ai.client.models.generate_content,
                model=ai.model_name,
                contents=prompt,
                config=config,
            )

        response = await ai._retry_call(_call)
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"Metadata generation failed: {e}")
        return {"error": str(e)}



async def main():
    import argparse

    style_choices = list(STYLE_PRESETS.keys())

    parser = argparse.ArgumentParser(description="Bible Animation Generator")
    parser.add_argument("topic", nargs="?", help="Bible topic (e.g., '창세기 1-3장')")
    parser.add_argument("--resume", type=str, help="Resume a previous run by ID")
    parser.add_argument("--script-only", action="store_true",
                        help="Only generate script (no TTS/render)")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="Target video duration in minutes (default: 10)")
    parser.add_argument("--style", type=str, default="pixar_disney",
                        choices=style_choices,
                        help=f"Visual style preset (default: pixar_disney). Options: {style_choices}")
    parser.add_argument("--regen-prompts", type=str, metavar="RUN_ID",
                        help="Regenerate only video prompts for an existing run (preserves TTS)")
    parser.add_argument("--char-sheet", type=str, metavar="CHARACTER_ID",
                        help="Print 360° character reference sheet prompt for a character")
    parser.add_argument("--char-json", type=str, metavar="CHARACTER_ID",
                        help="Print structured JSON metadata for a character")

    # --- Project (long-form) commands ---
    parser.add_argument("--new-project", type=str, metavar="TITLE",
                        help="Create a new long-form project")
    parser.add_argument("--scripture", type=str, default="",
                        help="Scripture reference for the project")
    parser.add_argument("--language", type=str, default="en",
                        help="Language for the project (default: en)")
    parser.add_argument("--project", type=str, metavar="SLUG",
                        help="Work on an existing project by slug")
    parser.add_argument("--chapter", type=int, metavar="N",
                        help="Chapter index to work on")
    parser.add_argument("--resume-chapter", action="store_true",
                        help="Resume a chapter (render + merge chapter)")
    parser.add_argument("--merge-project", action="store_true",
                        help="Merge all chapters into final master video")
    parser.add_argument("--project-status", action="store_true",
                        help="Show project status")
    parser.add_argument("--validate", action="store_true",
                        help="Validate chapter assets")
    parser.add_argument("--shorts", action="store_true",
                        help="Render 9:16 shorts version (use with --resume-chapter)")
    parser.add_argument("--generate-metadata", action="store_true",
                        help="Generate YouTube metadata (titles, thumbnails, descriptions, hashtags) for project + intro + shorts")
    parser.add_argument("--set-audio", nargs=2, metavar=("SCENES", "PRIORITY"),
                        help="Set audio priority for scenes. SCENES: comma-separated IDs or 'all'. PRIORITY: tts|veo|mix")
    parser.add_argument("--assemble-intro", action="store_true",
                        help="Auto-assemble ch00 intro from existing chapter scene videos")
    parser.add_argument("--validate-quality", action="store_true",
                        help="AI-powered visual quality analysis of all scene videos (uses Gemini 3 Flash)")

    args = parser.parse_args()

    # --- Character sheet prompt ---
    if args.char_sheet:
        char_db = CharacterDB()
        prompt = char_db.get_character_sheet_prompt(args.char_sheet)
        print("\n" + "=" * 60)
        print(f"360° CHARACTER SHEET PROMPT — {args.char_sheet}")
        print("=" * 60)
        print(prompt)
        print("=" * 60)
        return

    # --- Character JSON metadata ---
    if args.char_json:
        import json as _json
        char_db = CharacterDB()
        meta = char_db.get_json_metadata(args.char_json)
        print("\n" + "=" * 60)
        print(f"CHARACTER JSON METADATA — {args.char_json}")
        print("=" * 60)
        print(_json.dumps(meta, ensure_ascii=False, indent=2))
        print("=" * 60)
        return

    # --- Regenerate prompts only ---
    if args.regen_prompts:
        from api.services.prompts import format_scene_prompts_json

        run_id = args.regen_prompts
        pm = PathManager(run_id)

        if not os.path.exists(pm.script_file):
            logger.error(f"❌ No script.json found for run {run_id}")
            return

        with open(pm.script_file, "r", encoding="utf-8") as f:
            script_data = json.load(f)

        char_db = CharacterDB()
        script_gen = ScriptGenerator(
            character_db=char_db,
            style_preset=args.style,
        )

        # Regenerate prompts (preserves narration + TTS)
        updated = script_gen.regen_prompts(script_data, pm.root)

        # Also save JSON-structured prompts
        json_prompts_path = os.path.join(pm.root, "scene_prompts.json")
        json_text = format_scene_prompts_json(updated["scenes"], char_db)
        with open(json_prompts_path, "w", encoding="utf-8") as f:
            f.write(json_text)

        logger.info(f"✅ Prompts regenerated for {run_id}")
        logger.info(f"   Style: {args.style}")
        logger.info(f"   Text prompts: {pm.root}/scene_prompts.txt")
        logger.info(f"   JSON prompts: {json_prompts_path}")
        return

    # --- Project: Create new ---
    if args.new_project:
        slug = slugify(args.new_project)
        proj = ProjectManager(slug)

        if proj.project_data:
            logger.info(f"⚠️ Project '{slug}' already exists. Use --project {slug}")
            proj.print_status()
            return

        proj.create_project(
            title=args.new_project,
            scripture_ref=args.scripture,
            language=args.language,
            style_preset=args.style,
        )

        # Use AI to plan chapters
        logger.info("🤖 Planning chapters with AI...")
        ai = AIClient()
        chapter_plan = await ai.plan_chapters(
            title=args.new_project,
            scripture_ref=args.scripture,
            language=args.language,
        )
        proj.set_chapters(chapter_plan)
        proj.print_status()
        logger.info(f"\n✅ Project created! Next: generate scripts chapter by chapter:")
        logger.info(f"   python -m api.production.orchestrator --project {slug} --chapter 0")
        return

    # --- Project: Status ---
    if args.project and args.project_status:
        proj = ProjectManager(args.project)
        proj.print_status()
        return

    # --- Project: Generate YouTube Metadata ---
    if args.project and args.generate_metadata:
        await generate_project_metadata(args.project)
        return

    # --- Project: Assemble intro ---
    if args.project and getattr(args, 'assemble_intro', False):
        proj = ProjectManager(args.project)
        ch = proj.get_chapter(0)
        if not ch:
            logger.error("❌ Chapter 0 (introduction) not found in project")
            return
        
        cpm = proj.get_chapter_pm(0)
        style = proj.project_data.get("style_preset", "pixar_disney")
        
        orchestrator = BibleOrchestrator(
            run_id=proj.pm.slug,
            style_preset=style,
            path_manager=cpm,
        )
        orchestrator.chapter_context = {
            "language": proj.project_data.get("language", "en"),
        }
        orchestrator._load_existing_script()
        await orchestrator.assemble_intro(proj)
        return

    # --- Project: Validate ---
    if args.project and args.validate:
        proj = ProjectManager(args.project)
        logger.info(f"🔍 ═══ QC Validation: {proj.project_data.get('title', '')} ═══")

        total_scenes = 0
        total_duration = 0.0
        issues = []
        chapter_stats = []

        for ch in proj.get_all_chapters():
            idx = ch["index"]
            if idx == 0:
                continue

            cpm = proj.get_chapter_pm(idx)
            script_path = os.path.join(cpm.root, "script.json")
            prompts_path = os.path.join(cpm.root, "scene_prompts.txt")

            # File integrity
            if not os.path.exists(script_path):
                issues.append(f"ch{idx:02d}: script.json MISSING")
                chapter_stats.append(f"ch{idx:02d}: ❌ no script")
                continue

            if not os.path.exists(prompts_path):
                issues.append(f"ch{idx:02d}: scene_prompts.txt MISSING")

            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            scenes = script.get("scenes", [])
            num_scenes = len(scenes)
            total_scenes += num_scenes

            # Duration checks
            ch_duration = 0.0
            over_8s = 0
            missing_mp3 = 0
            missing_vtt = 0
            zero_mp3 = 0

            for scene in scenes:
                sid = scene.get("id", 0)
                dur = scene.get("duration", 0)
                ch_duration += dur
                if dur > 8:
                    over_8s += 1
                    issues.append(f"ch{idx:02d} scene {sid}: duration {dur}s > 8s")

                # MP3/VTT existence
                mp3 = cpm.get_audio_path(sid)
                vtt = cpm.get_vtt_path(sid)
                if not os.path.exists(mp3):
                    missing_mp3 += 1
                elif os.path.getsize(mp3) == 0:
                    zero_mp3 += 1
                    issues.append(f"ch{idx:02d} scene {sid}: audio_*.mp3 is 0 bytes")
                if not os.path.exists(vtt):
                    missing_vtt += 1

            total_duration += ch_duration

            # Duration target check
            target_str = ch.get("duration_target", "2m")
            target_secs = _parse_duration_target(target_str) * 60
            if target_secs > 0:
                deviation = abs(ch_duration - target_secs) / target_secs * 100
                if deviation > 10:
                    issues.append(
                        f"ch{idx:02d}: duration {ch_duration:.0f}s vs target "
                        f"{target_secs:.0f}s ({deviation:.0f}% deviation)"
                    )

            stat_line = (
                f"ch{idx:02d}: {num_scenes} scenes, {ch_duration:.0f}s"
            )
            if missing_mp3:
                stat_line += f", ⚠️{missing_mp3} missing MP3"
            if missing_vtt:
                stat_line += f", ⚠️{missing_vtt} missing VTT"
            if over_8s:
                stat_line += f", ⚠️{over_8s} over 8s"
            if zero_mp3:
                stat_line += f", ⚠️{zero_mp3} zero-byte MP3"
            chapter_stats.append(stat_line)

        # Print report
        logger.info("")
        logger.info("📊 ═══ Validation Report ═══")
        logger.info(f"프로젝트: {proj.project_data.get('title', '')}")
        logger.info(f"총 챕터: {len(chapter_stats)}")
        logger.info(f"총 씬: {total_scenes}")
        logger.info(f"총 Duration: ~{total_duration/60:.1f}분 ({total_duration:.0f}s)")
        logger.info("")
        logger.info("📋 챕터별:")
        for s in chapter_stats:
            logger.info(f"   {s}")

        if issues:
            logger.info("")
            logger.info(f"⚠️ Issues ({len(issues)}):")
            for issue in issues:
                logger.info(f"   ❗ {issue}")
        else:
            logger.info("")
            logger.info("✅ All checks passed! No issues found.")

        return

    # --- Project: Visual Quality Analysis ---
    if args.project and args.validate_quality:
        import subprocess as _sp
        proj = ProjectManager(args.project)

        # Add file logging so user can: tail -f <log_path>
        qa_log_path = os.path.join(proj.pm.root, "qa_log.txt")
        _fh = logging.FileHandler(qa_log_path, mode="w", encoding="utf-8")
        _fh.setFormatter(logging.Formatter("%(asctime)s - %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(_fh)

        logger.info(f"🔬 ═══ Visual Quality Analysis: {proj.project_data.get('title', '')} ═══")
        logger.info(f"📝 로그 파일: {qa_log_path}")
        logger.info(f"💡 터미널에서 실시간 확인: tail -f {qa_log_path}")
        ai = AIClient()
        if not ai.client:
            logger.error("❌ AI client not available. Cannot perform visual QA.")
            return

        qa_results = []
        total_pass = 0
        total_warn = 0
        total_fail = 0

        chapters = proj.get_all_chapters()

        # Pre-scan: count total scenes for progress tracking
        total_scene_count = 0
        for ch in chapters:
            sd = os.path.join(proj.get_chapter_pm(ch["index"]).root, "scenes")
            if os.path.isdir(sd):
                total_scene_count += len([f for f in os.listdir(sd) if f.startswith("scene_") and f.endswith(".mp4")])
        logger.info(f"📊 Total scenes to analyze: {total_scene_count}")
        analyzed_count = 0

        for ch in chapters:
            idx = ch["index"]
            cpm = proj.get_chapter_pm(idx)
            scenes_dir = os.path.join(cpm.root, "scenes")

            if not os.path.isdir(scenes_dir):
                logger.info(f"   ⏭️ ch{idx:02d}: No scenes directory")
                continue

            # Find scene_XXX.mp4 files
            scene_files = sorted([
                f for f in os.listdir(scenes_dir)
                if f.startswith("scene_") and f.endswith(".mp4")
            ])

            if not scene_files:
                logger.info(f"   ⏭️ ch{idx:02d}: No scene videos")
                continue

            logger.info(f"\n📂 ch{idx:02d} ({ch.get('title', '')}): {len(scene_files)} scenes")

            # Load script for scene context (narration + video prompt)
            script_path = os.path.join(cpm.root, "script.json")
            scene_contexts = {}
            scene_prompts = {}
            if os.path.exists(script_path):
                with open(script_path, "r", encoding="utf-8") as f:
                    script = json.load(f)
                for s in script.get("scenes", []):
                    sid = s.get("id", 0)
                    scene_contexts[sid] = s.get("narration", "")[:200]
                    scene_prompts[sid] = s.get("video_prompt", "")[:200]

            for si, scene_file in enumerate(scene_files, 1):
                analyzed_count += 1
                scene_path = os.path.join(scenes_dir, scene_file)

                # Extract scene ID from filename
                try:
                    sid = int(scene_file.replace("scene_", "").replace(".mp4", ""))
                except ValueError:
                    sid = 0

                # Extract middle keyframe
                keyframe_path = os.path.join(scenes_dir, f".qa_{scene_file.replace('.mp4', '.jpg')}")

                # Get duration, extract middle frame
                dur_result = _sp.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", scene_path],
                    stdout=_sp.PIPE, stderr=_sp.STDOUT
                )
                try:
                    dur = float(dur_result.stdout)
                except (ValueError, TypeError):
                    dur = 4.0

                mid_time = dur / 2.0
                _sp.run(
                    ["ffmpeg", "-y", "-nostdin", "-ss", str(mid_time),
                     "-i", scene_path, "-frames:v", "1", "-q:v", "2", keyframe_path],
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL
                )

                if not os.path.exists(keyframe_path):
                    logger.warning(f"   ⚠️ {scene_file}: Could not extract keyframe")
                    continue

                # Analyze with AI (narration + video prompt for Bible-aware context)
                context = scene_contexts.get(sid, "")
                vprompt = scene_prompts.get(sid, "")
                result = await ai.analyze_scene_quality(keyframe_path, context, vprompt)

                status = result.get("status", "WARN")
                score = result.get("score", 5)
                issues = result.get("issues", [])
                recommendation = result.get("recommendation", "")

                icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status, "❓")
                pct = analyzed_count / total_scene_count * 100 if total_scene_count else 0
                logger.info(f"   {icon} [{analyzed_count}/{total_scene_count} ({pct:.0f}%)] {scene_file}: {status} (Score: {score}/10)")
                if issues:
                    for issue in issues:
                        logger.info(f"      → {issue}")

                if status == "PASS":
                    total_pass += 1
                elif status == "WARN":
                    total_warn += 1
                else:
                    total_fail += 1

                qa_results.append({
                    "chapter": idx,
                    "chapter_title": ch.get("title", ""),
                    "scene": scene_file,
                    "scene_id": sid,
                    "status": status,
                    "score": score,
                    "issues": issues,
                    "recommendation": recommendation,
                })

                # Remove temp keyframe
                os.remove(keyframe_path)

        # Generate qa_report.md
        report_path = os.path.join(proj.pm.root, "qa_report.md")
        total = total_pass + total_warn + total_fail
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# Visual Quality Report\n\n")
            f.write(f"**Project**: {proj.project_data.get('title', '')}\n")
            f.write(f"**Model**: {ai.model_name}\n")
            f.write(f"**Total Scenes Analyzed**: {total}\n\n")
            f.write(f"| Status | Count | Percentage |\n")
            f.write(f"|--------|-------|------------|\n")
            if total > 0:
                f.write(f"| ✅ PASS | {total_pass} | {total_pass/total*100:.0f}% |\n")
                f.write(f"| ⚠️ WARN | {total_warn} | {total_warn/total*100:.0f}% |\n")
                f.write(f"| ❌ FAIL | {total_fail} | {total_fail/total*100:.0f}% |\n")
            f.write(f"\n---\n\n")

            # Full summary table (user requested)
            f.write(f"## Scene-by-Scene Summary\n\n")
            f.write(f"| Chapter | Scene | Score | Status | Action | Key Issue |\n")
            f.write(f"|---------|-------|-------|--------|--------|-----------|\n")
            for r in qa_results:
                icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(r["status"], "❓")
                action = {"PASS": "OK", "WARN": "Review", "FAIL": "**Regenerate**"}.get(r["status"], "?")
                key_issue = r["issues"][0][:60] if r["issues"] else "—"
                f.write(f"| ch{r['chapter']:02d} | {r['scene']} | {r['score']}/10 | {icon} {r['status']} | {action} | {key_issue} |\n")
            f.write(f"\n---\n\n")

            # Detailed issues (FAIL first, then WARN)
            for status_filter in ["FAIL", "WARN"]:
                filtered = [r for r in qa_results if r["status"] == status_filter]
                if not filtered:
                    continue
                icon = {"WARN": "⚠️", "FAIL": "❌"}[status_filter]
                f.write(f"## {icon} {status_filter} Details ({len(filtered)} scenes)\n\n")
                for r in filtered:
                    f.write(f"### ch{r['chapter']:02d} / {r['scene']} (Score: {r['score']}/10)\n")
                    if r["issues"]:
                        for issue in r["issues"]:
                            f.write(f"- {issue}\n")
                    if r["recommendation"]:
                        f.write(f"- **Recommendation**: {r['recommendation']}\n")
                    f.write(f"\n")

        logger.info(f"\n📊 ═══ Visual QA Summary ═══")
        logger.info(f"✅ PASS: {total_pass}  ⚠️ WARN: {total_warn}  ❌ FAIL: {total_fail}")
        logger.info(f"📄 Report saved: {report_path}")
        return

    # --- Project: Merge all chapters ---
    if args.project and args.merge_project:
        proj = ProjectManager(args.project)
        output = proj.merge_all_chapters()
        if output:
            logger.info(f"🎬 Final video: {output}")

            # Generate project-level metadata
            logger.info("📦 Generating YouTube metadata...")
            ai = AIClient()
            timestamps = proj.generate_chapter_timestamps()
            metadata = await ai.generate_project_metadata(
                project_data=proj.project_data,
                timestamps=timestamps,
            )
            metadata_path = proj.pm.metadata_file
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ Metadata saved: {metadata_path}")
        return

    # --- Set audio priority for scenes ---
    if args.set_audio and args.project and args.chapter is not None:
        scenes_str, priority = args.set_audio
        if priority not in ("tts", "veo", "mix"):
            logger.error(f"❌ Invalid priority: {priority}. Must be tts|veo|mix")
            return

        proj = ProjectManager(args.project)
        cpm = proj.get_chapter_pm(args.chapter)
        script_path = os.path.join(cpm.root, "script.json")

        if not os.path.exists(script_path):
            logger.error(f"❌ No script.json found at {script_path}")
            return

        with open(script_path, "r", encoding="utf-8") as f:
            script_data = json.load(f)

        scenes = script_data.get("scenes", [])

        if scenes_str.lower() == "all":
            target_ids = [s["id"] for s in scenes]
        else:
            target_ids = [int(x.strip()) for x in scenes_str.split(",")]

        updated = 0
        for scene in scenes:
            if scene["id"] in target_ids:
                scene["audio_priority"] = priority
                updated += 1

        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Updated {updated} scenes to audio_priority='{priority}'")
        for scene in scenes:
            if scene["id"] in target_ids:
                narr = scene.get("narration", "")[:50]
                logger.info(f"   Scene {scene['id']}: [{priority}] {narr}...")
        return

    # --- Project: Work on chapter ---
    if args.project and args.chapter is not None:
        proj = ProjectManager(args.project)
        ch = proj.get_chapter(args.chapter)
        if not ch:
            logger.error(f"❌ Chapter {args.chapter} not found")
            proj.print_status()
            return

        cpm = proj.get_chapter_pm(args.chapter)
        style = proj.project_data.get("style_preset", "pixar_disney")

        if args.resume_chapter:
            # Resume: render + merge chapter
            shorts = getattr(args, 'shorts', False)
            mode_label = " (SHORTS 9:16)" if shorts else ""
            logger.info(f"▶️ Resuming chapter {args.chapter}: {ch['title']}{mode_label}")
            orchestrator = BibleOrchestrator(
                run_id=proj.pm.slug,
                style_preset=style,
                path_manager=cpm,
            )
            orchestrator.chapter_context = {
                "language": proj.project_data.get("language", "en"),
            }
            orchestrator.shorts_mode = shorts
            orchestrator._load_existing_script()
            if not shorts:
                await orchestrator.generate_tts_assets()
            else:
                logger.info("📐 Shorts mode: skipping TTS (reusing existing), rendering 9:16")
            render_ok = await orchestrator.render_all()
            if render_ok:
                output = orchestrator.merge_clips()
                if output:
                    proj.update_chapter_status(args.chapter, "rendered")
                    logger.info(f"✅ Chapter {args.chapter} rendered: {output}")
                    logger.info(f"   Next chapter or merge project:")
                    next_ch = proj.get_next_pending()
                    if next_ch:
                        logger.info(
                            f"   python -m api.production.orchestrator "
                            f"--project {args.project} --chapter {next_ch['index']}"
                        )
                    else:
                        logger.info(
                            f"   python -m api.production.orchestrator "
                            f"--project {args.project} --merge-project"
                        )
        else:
            # Generate script + TTS for this chapter
            logger.info(
                f"📝 Generating chapter {args.chapter}: {ch['title']}"
            )
            orchestrator = BibleOrchestrator(
                book=proj.project_data.get("scripture_ref", ""),
                chapter=ch["title"],
                target_duration=_parse_duration_target(ch.get("duration_target", "2m")),
                style_preset=style,
                path_manager=cpm,
            )

            # Build chapter context
            previous_chapters = [
                c for c in proj.get_all_chapters()
                if c["index"] < args.chapter
            ]
            chapter_context = {
                "project_title": proj.project_data["title"],
                "scripture_ref": proj.project_data["scripture_ref"],
                "language": proj.project_data.get("language", "en"),
                "chapter_index": args.chapter,
                "chapter_title": ch["title"],
                "chapter_key_events": ch.get("key_events", ""),
                "chapter_scripture_range": ch.get("scripture_range", ""),
                "duration_target": ch.get("duration_target", "2m"),
                "total_chapters": len(proj.get_all_chapters()),
                "previous_chapters": [
                    {"title": c["title"], "key_events": c.get("key_events", "")}
                    for c in previous_chapters
                ],
            }

            # Set chapter context for script generation
            orchestrator.chapter_context = chapter_context
            await orchestrator.run(mode="full")

            # Update status
            if os.path.exists(cpm.script_file):
                proj.update_chapter_status(args.chapter, "tts_done")

        return

    # --- Resume (legacy single-run) ---
    if args.resume:
        orchestrator = BibleOrchestrator(run_id=args.resume, style_preset=args.style)
        await orchestrator.run(mode="resume")

    # --- New run (legacy) ---
    elif args.topic:
        topic = args.topic.strip()
        parts = topic.split()
        book = parts[0] if parts else topic
        chapter = " ".join(parts[1:]) if len(parts) > 1 else "전체"

        mode = "script-only" if args.script_only else "full"

        orchestrator = BibleOrchestrator(
            book=book,
            chapter=chapter,
            target_duration=args.duration,
            style_preset=args.style,
        )
        await orchestrator.run(mode=mode)

    else:
        parser.print_help()
        print("\n📋 Available style presets:")
        for key, preset in STYLE_PRESETS.items():
            print(f"   --style {key:20s} → {preset['name']}")
        print("\n🔧 Utility commands:")
        print("   --char-sheet david      → Print 360° character sheet prompt")
        print("   --char-json david        → Print structured JSON metadata")
        print("   --regen-prompts RUN_ID   → Regenerate prompts for existing run")


if __name__ == "__main__":
    asyncio.run(main())
