"""
Bible Script Generator.
Integrates AI + CharacterDB + StylePresets to produce complete scene scripts
with character consistency and configurable visual styles.
"""

import json
import os
import logging
from typing import Optional

from api.services.ai import AIClient
from api.production.character_db import CharacterDB
from api.services.prompts import format_scene_prompts_txt
from config.settings import get_style_preset, BIBLE_CONFIG

logger = logging.getLogger("script_generator")


class ScriptGenerator:
    """Generates Bible animation scripts with character consistency and style presets."""

    def __init__(self, ai_client: Optional[AIClient] = None,
                 character_db: Optional[CharacterDB] = None,
                 style_preset: str = "pixar_disney"):
        self.ai = ai_client or AIClient()
        self.char_db = character_db or CharacterDB()
        self.style_preset_name = style_preset
        self.style = get_style_preset(style_preset)

    async def generate(
        self,
        book: str,
        chapter: str,
        target_duration: float = 10.0,
        output_dir: Optional[str] = None,
        chapter_context: Optional[dict] = None,
    ) -> dict:
        """
        Full script generation pipeline:
        1. Episode planning
        2. Character extraction
        3. Scene-by-scene script generation
        4. Quality review
        5. Apply style + character consistency
        6. Save script.json + scene_prompts.txt

        Returns: {"plan": dict, "scenes": list, "script_path": str, "prompts_path": str}
        """
        logger.info(f"📖 Starting script generation: {book} {chapter}")
        logger.info(f"🎨 Style preset: {self.style['name']}")

        # Build context string for chapter-based projects
        context = ""
        if chapter_context:
            ctx = chapter_context
            lang = ctx.get("language", "en")
            context_parts = [
                f"Project: {ctx.get('project_title', '')}",
                f"Language: {'English' if lang == 'en' else 'Korean' if lang == 'ko' else lang}",
                f"Scripture: {ctx.get('scripture_ref', '')}",
                f"Chapter {ctx.get('chapter_index', 0)} of {ctx.get('total_chapters', '?')}: {ctx.get('chapter_title', '')}",
                f"Key events for this chapter: {ctx.get('chapter_key_events', '')}",
                f"Scripture range: {ctx.get('chapter_scripture_range', '')}",
                f"Target duration: {ctx.get('duration_target', '2m')}",
            ]
            prev = ctx.get("previous_chapters", [])
            if prev:
                context_parts.append("Previous chapters:")
                for pc in prev:
                    context_parts.append(f"  - {pc['title']}: {pc.get('key_events', '')}")
            context = "\n".join(context_parts)
            logger.info(f"📋 Chapter context:\n{context}")

        # 1. Generate episode plan
        logger.info("🧠 Phase 1: Episode Planning...")
        plan = await self.ai.generate_bible_plan(book, chapter, context=context)
        episode = plan.get("episode", {})
        logger.info(f"✅ Plan: {episode.get('title_ko', 'Unknown')}")

        # 2. Identify characters and build prompt fragments
        key_chars = episode.get("key_characters", [])
        logger.info(f"👥 Characters in episode: {key_chars}")

        # Build both standard and stream descriptions
        char_descriptions = self._build_character_descriptions(key_chars)
        char_bible = self.char_db.get_character_bible_markdown(key_chars)

        # 2.5. Build scene budget from key_events (if structured)
        scene_budget = ""
        if chapter_context:
            key_events = chapter_context.get("chapter_key_events", "")
            target_secs = target_duration * 60

            if isinstance(key_events, list) and key_events:
                # New format: list of dicts with weight/type/must_include_quotes
                budget_lines = []
                for evt in key_events:
                    event_name = evt.get("event", "")
                    weight = evt.get("weight", 1.0 / len(key_events))
                    evt_type = evt.get("type", "normal")
                    alloc_secs = int(target_secs * weight)
                    alloc_scenes = max(1, alloc_secs // 7)
                    tag = " [CLIMAX]" if evt_type == "climax" else ""
                    budget_lines.append(
                        f"- {event_name}: ~{alloc_scenes} scenes / ~{alloc_secs}s ({int(weight*100)}%){tag}"
                    )
                    quotes = evt.get("must_include_quotes", [])
                    for q in quotes:
                        budget_lines.append(f'  [MUST-INCLUDE] "{q}"')

                scene_budget = "\n".join(budget_lines)
                logger.info(f"📊 Scene budget:\n{scene_budget}")
            elif isinstance(key_events, str) and key_events:
                # Old format: plain string — add general distribution guidance
                scene_budget = (
                    f"Story events: {key_events}\n"
                    f"Total budget: ~{int(target_secs)}s / ~{int(target_secs // 7)} scenes\n"
                    "RULE: Allocate at least 30% of scenes to the most dramatic/climactic events.\n"
                    "RULE: Do NOT spend more than 40% on dialogue/persuasion scenes.\n"
                    "RULE: Action sequences (battles, miracles) should be expanded with varied camera angles."
                )

        # 3. Generate scene-by-scene script
        logger.info("✍️ Phase 2: Script Generation...")
        scenes = await self.ai.generate_bible_script(
            plan=plan,
            character_descriptions=char_descriptions,
            target_duration_minutes=target_duration,
            scene_budget=scene_budget,
        )

        if not scenes:
            logger.error("❌ No scenes generated!")
            return {"plan": plan, "scenes": [], "script_path": None, "prompts_path": None}

        # 4. Quality review
        logger.info("🔍 Phase 3: Quality Review...")
        scenes = await self.ai.refine_script(scenes, char_descriptions)

        # 5. Apply character consistency + style preset
        logger.info("🎨 Phase 4: Applying Character Consistency + Style...")
        scenes = self._apply_consistency_and_style(scenes)

        # 6. Save outputs
        script_data = {
            "plan": plan,
            "scenes": scenes,
            "characters": key_chars,
            "style_preset": self.style_preset_name,
            "target_duration_minutes": target_duration,
        }

        script_path = None
        prompts_path = None

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

            # Save script.json
            script_path = os.path.join(output_dir, "script.json")
            with open(script_path, "w", encoding="utf-8") as f:
                json.dump(script_data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 Script saved: {script_path}")

            # Save scene_prompts.txt
            prompts_path = os.path.join(output_dir, "scene_prompts.txt")
            prompts_text = format_scene_prompts_txt(scenes)
            with open(prompts_path, "w", encoding="utf-8") as f:
                f.write(prompts_text)
            logger.info(f"📝 Scene prompts saved: {prompts_path}")

            # Save scene_prompts2.txt (single-line per scene)
            prompts2_path = os.path.join(output_dir, "scene_prompts2.txt")
            self._save_single_line_prompts(prompts_text, prompts2_path)
            logger.info(f"📝 Single-line prompts saved: {prompts2_path}")

            # Copy character DB to run directory
            char_db_path = os.path.join(output_dir, "character_db.json")
            self.char_db.copy_to_run(char_db_path)

        logger.info(f"✅ Script generation complete: {len(scenes)} scenes")

        return {
            "plan": plan,
            "scenes": scenes,
            "script_path": script_path,
            "prompts_path": prompts_path,
        }

    def regen_prompts(self, script_data: dict, output_dir: str) -> dict:
        """
        Regenerate only the video prompts (style + consistency) for an existing script.
        Preserves narration, TTS durations, and all audio assets.

        Args:
            script_data: Existing script.json content
            output_dir: Run directory

        Returns: Updated script_data
        """
        logger.info(f"🔄 Regenerating prompts with style: {self.style['name']}")

        scenes = script_data.get("scenes", [])
        if not scenes:
            logger.error("❌ No scenes to regenerate!")
            return script_data

        # Apply consistency and style
        scenes = self._apply_consistency_and_style(scenes)
        script_data["scenes"] = scenes
        script_data["style_preset"] = self.style_preset_name

        # Save updated script.json
        script_path = os.path.join(output_dir, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Updated script: {script_path}")

        # Save updated scene_prompts.txt
        prompts_path = os.path.join(output_dir, "scene_prompts.txt")
        prompts_text = format_scene_prompts_txt(scenes)
        with open(prompts_path, "w", encoding="utf-8") as f:
            f.write(prompts_text)
        logger.info(f"📝 Updated scene prompts: {prompts_path}")

        # Save updated scene_prompts2.txt (single-line per scene)
        prompts2_path = os.path.join(output_dir, "scene_prompts2.txt")
        self._save_single_line_prompts(prompts_text, prompts2_path)
        logger.info(f"📝 Updated single-line prompts: {prompts2_path}")

        return script_data

    @staticmethod
    def _save_single_line_prompts(prompts_text: str, output_path: str):
        """Save prompts in single-line-per-scene format (for easy copy-paste to Veo)."""
        lines = prompts_text.strip().split('\n')
        scenes = []
        current = []
        for line in lines:
            if line.strip() == '':
                if current:
                    scenes.append(' '.join(current))
                    current = []
            else:
                current.append(line.strip())
        if current:
            scenes.append(' '.join(current))
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(scenes) + '\n')

    def _build_character_descriptions(self, character_ids: list) -> str:
        """Build a comprehensive character description string for prompts."""
        descriptions = []
        for cid in character_ids:
            frag = self.char_db.get_prompt_fragment(cid)
            descriptions.append(frag)

        if not descriptions:
            return "No specific characters identified. Use generic biblical figures."

        return "\n\n".join(descriptions)

    def _apply_consistency_and_style(self, scenes: list) -> list:
        """
        Post-process all scenes to apply:
        1. Character stream descriptions (uninterrupted stream for identity)
        2. Style preset (consistent visual anchor)
        3. Negative guidance (drift prevention)
        4. Dialogue detection (skip TTS/VTT for dialogue-heavy scenes)
        """
        style_anchor = self.style["style_anchor"]
        style_negative = self.style["negative"]

        for scene in scenes:
            vp = scene.get("video_prompt", {})
            if not isinstance(vp, dict):
                continue

            # 1. Inject style preset
            vp["style"] = style_anchor

            # 2. Build combined negative (style + character-specific)
            negatives = [style_negative]
            chars = scene.get("characters", [])
            for cid in chars:
                char_neg = self.char_db.get_negative_guidance(cid)
                if char_neg:
                    negatives.append(char_neg)
            vp["negative"] = ". ".join(filter(None, negatives))

            # 3. Replace character descriptions in objects with stream versions
            objects = vp.get("objects", "")
            for cid in chars:
                ch = self.char_db.find_by_name(cid)
                if ch:
                    anchor = ch.get("anchor_name", ch["name_en"])
                    stream = self.char_db.get_stream_fragment(cid)
                    if anchor not in objects and ch["name_en"] in objects:
                        old_name = ch["name_en"]
                        vp["objects"] = objects.replace(
                            old_name, f"{stream}", 1
                        )
                        objects = vp["objects"]

            scene["video_prompt"] = vp

            # 4. Dialogue detection
            narration = scene.get("narration", "")
            action = vp.get("action", "")
            detection = self._detect_dialogue(narration, action)
            scene["has_dialogue"] = detection["has_dialogue"]
            scene["dialogue_ratio"] = detection["dialogue_ratio"]
            scene["skip_tts"] = detection["has_dialogue"]

        return scenes

    @staticmethod
    def _detect_dialogue(narration: str, action: str) -> dict:
        """
        Detect if a scene is dialogue-heavy using combined heuristics.
        Returns: {"has_dialogue": bool, "dialogue_ratio": float, "signals": list}

        Three methods combined:
          1. Quote patterns — Korean/English/CJK quotation marks in narration
          2. Speech verbs — Korean + English verbs indicating spoken dialogue
          3. Action keywords — visual cues of characters speaking in action field
        Score >= 2 → dialogue scene.
        """
        import re

        score = 0
        signals = []

        # --- Method 1: Quote patterns in narration ---
        quote_patterns = [
            r'"[^"]{3,}"',       # "대사"
            r"'[^']{3,}'",       # '대사'
            r'「[^」]{2,}」',      # 「대사」
            r'『[^』]{2,}』',      # 『대사』
            r'"[^"]{3,}"',       # "대사"  (smart quotes)
            r"'[^']{3,}'",       # '대사'  (smart quotes)
        ]
        quoted_chars = 0
        total_chars = max(len(narration), 1)
        for pat in quote_patterns:
            matches = re.findall(pat, narration)
            for m in matches:
                quoted_chars += len(m)
        dialogue_ratio = min(quoted_chars / total_chars, 1.0)

        if dialogue_ratio > 0.3:
            score += 2
            signals.append(f"quotes:{dialogue_ratio:.0%}")
        elif dialogue_ratio > 0.1:
            score += 1
            signals.append(f"some_quotes:{dialogue_ratio:.0%}")

        # --- Method 2: Speech verbs ---
        ko_speech_verbs = [
            "말했", "외쳤", "소리쳤", "대답했", "물었",
            "속삭였", "선언했", "명령했", "부르짖",
            "고함쳤", "중얼거", "읊었", "노래했",
            "말씀하", "이르시", "가라사대", "대답하여", "이르되",
        ]
        en_speech_verbs = [
            "said", "says", "shouted", "cried", "exclaimed",
            "whispered", "declared", "commanded", "called out",
            "spoke", "replied", "answered", "asked", "yelled",
        ]

        narration_lower = narration.lower()
        ko_verb_count = sum(1 for v in ko_speech_verbs if v in narration)
        en_verb_count = sum(1 for v in en_speech_verbs if v in narration_lower)
        verb_count = ko_verb_count + en_verb_count

        if verb_count >= 3:
            score += 2
            signals.append(f"speech_verbs:{verb_count}")
        elif verb_count >= 1:
            score += 1
            signals.append(f"speech_verb:{verb_count}")

        # --- Method 3: Action field keywords ---
        action_lower = action.lower()
        action_keywords = [
            "speaking", "talking", "says", "shouts", "dialogue",
            "conversation", "arguing", "pleading", "confronting",
            "announces", "proclaims", "roaring his challenge",
            "voice ringing", "voice echoing",
            "대화", "말하", "외치", "선언",
        ]
        action_hits = sum(1 for kw in action_keywords if kw in action_lower)

        if action_hits >= 2:
            score += 2
            signals.append(f"action_keywords:{action_hits}")
        elif action_hits >= 1:
            score += 1
            signals.append(f"action_keyword:{action_hits}")

        return {
            "has_dialogue": score >= 2,
            "dialogue_ratio": round(dialogue_ratio, 3),
            "score": score,
            "signals": signals,
        }
