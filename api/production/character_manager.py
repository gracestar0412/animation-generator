"""
Character Manager for Bible Animation Projects.

Phase 4 of the production pipeline:
  1. Analyze character timelines across all chapters
  2. Generate era-based visual anchors via Gemini
  3. Generate character reference sheets (era-aware, with reuse)
  4. Inject visual anchors into scene_prompts

Usage:
  python -m api.production.character_manager --project david_and_goliath
"""

import asyncio
import os
import sys
import json
import re
import shutil
import logging
from typing import Optional

from api.production.project_manager import ProjectManager
from api.production.character_db import CharacterDB
from api.services.ai_client import AIClient
from api.services.prompts import format_scene_prompts_txt
from api.production.script_generator import ScriptGenerator
from config.settings import get_style_preset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("CharacterManager")


class CharacterManager:
    """
    Manages character identity across all chapters of a project.

    Key responsibilities:
      - Timeline analysis: track character appearances and era changes
      - Era-based sheets: generate different sheets for different life stages
      - Sheet reuse: copy same-era sheets across chapters
      - Visual anchor injection: inline character descriptions into scene prompts
    """

    def __init__(self, project_slug: str):
        self.proj = ProjectManager(project_slug)
        self.char_db = CharacterDB()
        self.ai = AIClient()
        self.style = get_style_preset(
            self.proj.project_data.get("style_preset", "pixar_disney")
        )

        # Output paths
        self.timeline_path = os.path.join(
            self.proj.pm.root, "character_timeline.json"
        )
        self.anchors_path = os.path.join(
            self.proj.pm.root, "character_visual_anchors.json"
        )

        self.timeline = {}
        self.visual_anchors = {}

    # ------------------------------------------------------------------ #
    #  Step 1: Character Timeline Analysis
    # ------------------------------------------------------------------ #

    def analyze_timeline(self) -> dict:
        """
        Analyze all script.json files to build character timeline.

        Result format:
        {
          "DAVID": {
            "total_appearances": 85,
            "chapters": { "1": 12, "3": 25, ... },
            "phases": [
              { "era": "shepherd_boy", "age": "~15-17", "chapters": [1,2,3] },
              { "era": "fugitive_warrior", "age": "~20-28", "chapters": [4,5,...] }
            ]
          }
        }
        """
        logger.info("📊 Step 1: Analyzing character timeline across all chapters...")

        char_data = {}  # char_id -> { chapters: {ch_idx: count}, descriptions: [...] }

        for ch in self.proj.get_all_chapters():
            idx = ch["index"]
            if idx == 0:
                continue

            cpm = self.proj.get_chapter_pm(idx)
            script_path = os.path.join(cpm.root, "script.json")
            if not os.path.exists(script_path):
                continue

            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)

            for scene in script.get("scenes", []):
                for cid in scene.get("characters", []):
                    # Normalize character ID
                    norm_id = self._normalize_char_id(cid)

                    if norm_id not in char_data:
                        char_data[norm_id] = {
                            "original_ids": set(),
                            "chapters": {},
                            "descriptions": [],
                        }

                    char_data[norm_id]["original_ids"].add(cid)
                    char_data[norm_id]["chapters"][idx] = (
                        char_data[norm_id]["chapters"].get(idx, 0) + 1
                    )

                    # Collect scene descriptions for this character
                    objects_text = scene.get("objects", "")
                    if cid.lower() in objects_text.lower():
                        char_data[norm_id]["descriptions"].append({
                            "chapter": idx,
                            "text": objects_text,
                        })

        # Build timeline
        self.timeline = {}
        for norm_id, data in sorted(
            char_data.items(),
            key=lambda x: sum(x[1]["chapters"].values()),
            reverse=True,
        ):
            total = sum(data["chapters"].values())
            chapter_list = sorted(data["chapters"].keys())

            self.timeline[norm_id] = {
                "total_appearances": total,
                "original_ids": sorted(data["original_ids"]),
                "chapters": data["chapters"],
                "chapter_list": chapter_list,
                "phases": [],  # Will be populated in step 2
            }

        # Save timeline
        with open(self.timeline_path, "w", encoding="utf-8") as f:
            json.dump(self.timeline, f, ensure_ascii=False, indent=2)

        logger.info(
            f"✅ Timeline: {len(self.timeline)} characters across "
            f"{len(self.proj.get_all_chapters())-1} chapters"
        )
        for cid, data in list(self.timeline.items())[:10]:
            chs = ",".join(str(c) for c in data["chapter_list"])
            logger.info(f"   {cid}: {data['total_appearances']} appearances (ch{chs})")

        return self.timeline

    def _normalize_char_id(self, cid: str) -> str:
        """Normalize character IDs to canonical form."""
        # Strip known suffixes/prefixes
        normalized = cid.strip()

        # Map common variants to canonical names
        mappings = {
            "DAVID_SHEPHERD_YOUTHFUL": "DAVID",
            "DAVID_YOUNG_WARRIOR": "DAVID",
            "DAVID_WARRIOR": "DAVID",
            "david_young": "DAVID",
            "David": "DAVID",
            "KING SAUL": "SAUL",
            "KING_SAUL": "SAUL",
            "saul_king": "SAUL",
            "Saul": "SAUL",
            "jonathan_prince": "JONATHAN",
            "Jonathan": "JONATHAN",
            "michal_princess": "MICHAL",
            "Michal": "MICHAL",
            "SAMUEL_PROPHET_OLD_WISE": "SAMUEL",
            "Samuel": "SAMUEL",
            "JESSE_ELDER_FATHER": "JESSE",
            "ELIAB_SON_TALL_STRONG": "ELIAB",
            "ELIAB_SON": "ELIAB",
            "ABINADAB_SON": "ABINADAB",
            "SHAMMAH_SON": "SHAMMAH",
            "GOD_VOICE_UNSEEN": "GOD_VOICE",
            "EVIL_SPIRIT_SHADOW_PRESENCE": "EVIL_SPIRIT",
            "KING SAUL_MIDDLE_AGED_BEARDED_ROYAL_ROBES_CROWN_SWORD": "SAUL",
            "DAVID_LOYAL_FOLLOWERS_ROUGH_APPEARANCE_VARIOUS_AGES_SIMPLE_TUNICS_LEATHER_ARMOR_SWORDS_SPEARS": "DAVIDS_FOLLOWERS",
            "DAVID'S MEN": "DAVIDS_FOLLOWERS",
            "DAVID'S_MEN": "DAVIDS_FOLLOWERS",
            "David's Loyal Men": "DAVIDS_FOLLOWERS",
            "SAUL_KING_TROUBLED": "SAUL",
            "King Saul": "SAUL",
            "King Achish": "ACHISH",
            "Achish": "ACHISH",
        }

        if normalized in mappings:
            return mappings[normalized]

        # Default: uppercase, strip long descriptive suffixes
        upper = normalized.upper().replace(" ", "_").replace("'", "")
        # Remove long suffixes after known patterns
        for suffix in ["_MIDDLE_AGED", "_CLEAN_SHAVEN", "_ROUGH_APPEARANCE"]:
            if suffix in upper:
                upper = upper[:upper.index(suffix)]
        return upper

    # ------------------------------------------------------------------ #
    #  Step 2: Generate Visual Anchors via Gemini
    # ------------------------------------------------------------------ #

    async def generate_visual_anchors(self) -> dict:
        """
        Use Gemini to analyze character descriptions and generate
        era-specific visual anchors.

        For characters who appear across many chapters, Gemini will
        identify distinct life stages (eras) and generate fixed
        appearance descriptions for each.
        """
        logger.info("🎨 Step 2: Generating visual anchors via Gemini...")

        if not self.timeline:
            if os.path.exists(self.timeline_path):
                with open(self.timeline_path, "r", encoding="utf-8") as f:
                    self.timeline = json.load(f)
            else:
                self.analyze_timeline()

        # Prepare character summaries for Gemini
        char_summaries = []
        for cid, data in self.timeline.items():
            if data["total_appearances"] < 2:
                continue
            chapters = data["chapter_list"]

            # Get existing description from CharacterDB
            ch_data = self.char_db.characters.get(cid.lower())
            if not ch_data:
                ch_data = self.char_db.find_by_name(cid)
            existing_desc = ""
            if ch_data:
                existing_desc = (
                    f"Existing description: {ch_data.get('appearance', '')} "
                    f"Clothing: {ch_data.get('clothing', '')}"
                )

            char_summaries.append(
                f"- {cid}: appears {data['total_appearances']} times in chapters "
                f"{chapters}. {existing_desc}"
            )

        if not char_summaries:
            logger.info("⏭️ No major characters found for anchor generation")
            return {}

        prompt = f"""Analyze these Bible animation characters and their chapter appearances.
For each character, determine their life stages (eras) based on the story progression.

Project: {self.proj.project_data.get('title', '')}
Scripture: {self.proj.project_data.get('scripture_ref', '')}

Characters:
{chr(10).join(char_summaries)}

For each character, output a JSON object with this structure:
{{
  "CHARACTER_NAME": {{
    "phases": [
      {{
        "era": "short_era_label",
        "age": "approximate age range",
        "chapters": [list of chapter indices],
        "visual_anchor": "Detailed physical description for this era. Include: age, build, skin tone, hair style/color, facial features, typical clothing. This must be a single flowing description with no commas, using 'and' to join attributes."
      }}
    ]
  }}
}}

Rules:
- If a character doesn't change visually across chapters, use a single phase with era "single"
- David specifically changes: shepherd boy (ch1-3) → young warrior (ch4-9) → emerging king (ch10-12)
- Saul changes: powerful king (ch1-4) → increasingly troubled (ch5-9) → tragic decline (ch10)
- Minor characters (< 5 appearances) get a single "single" phase
- The visual_anchor text must NOT contain any commas — use "and" instead
- Include specific details: hair color, skin tone, build, distinctive features

Return ONLY the JSON object, no markdown formatting."""

        try:
            response = await self.ai.generate_text(prompt)
            # Parse JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                self.visual_anchors = json.loads(json_match.group())
            else:
                logger.warning("⚠️ Could not parse Gemini response as JSON")
                self.visual_anchors = {}
        except Exception as e:
            logger.warning(f"⚠️ Gemini visual anchor generation failed: {e}")
            self.visual_anchors = {}

        # Merge phases back into timeline
        for cid, anchor_data in self.visual_anchors.items():
            if cid in self.timeline:
                self.timeline[cid]["phases"] = anchor_data.get("phases", [])

        # Save
        with open(self.anchors_path, "w", encoding="utf-8") as f:
            json.dump(self.visual_anchors, f, ensure_ascii=False, indent=2)

        with open(self.timeline_path, "w", encoding="utf-8") as f:
            json.dump(self.timeline, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Visual anchors generated for {len(self.visual_anchors)} characters")
        for cid, data in self.visual_anchors.items():
            phases = data.get("phases", [])
            eras = ", ".join(p["era"] for p in phases)
            logger.info(f"   {cid}: {len(phases)} era(s) — {eras}")

        return self.visual_anchors

    # ------------------------------------------------------------------ #
    #  Step 3: Generate Character Sheets (era-aware)
    # ------------------------------------------------------------------ #

    async def generate_sheets(self):
        """
        Generate character reference sheets with era-aware strategy:
        - Same era across chapters → generate once, copy
        - Different eras → separate sheet per era
        - Minor characters → group sheet
        """
        logger.info("🖼️ Step 3: Generating era-aware character sheets...")

        if not self.visual_anchors:
            if os.path.exists(self.anchors_path):
                with open(self.anchors_path, "r", encoding="utf-8") as f:
                    self.visual_anchors = json.load(f)
        if not self.timeline:
            if os.path.exists(self.timeline_path):
                with open(self.timeline_path, "r", encoding="utf-8") as f:
                    self.timeline = json.load(f)

        style_desc = self.style.get("style_anchor", "")

        # Build sheet plan: which sheets to generate and where to copy
        sheet_plan = {}  # "CHAR_era" -> { prompt, target_chapters, source_chapter }

        for cid, anchor_data in self.visual_anchors.items():
            phases = anchor_data.get("phases", [])
            if not phases:
                continue

            for phase in phases:
                era = phase.get("era", "single")
                chapters = phase.get("chapters", [])
                visual_anchor = phase.get("visual_anchor", "")
                age = phase.get("age", "")

                if not chapters or not visual_anchor:
                    continue

                sheet_key = f"{cid}_{era}"
                source_ch = chapters[0]  # Generate in first chapter of this era
                freq = sum(
                    self.timeline.get(cid, {}).get("chapters", {}).get(c, 0)
                    for c in chapters
                )

                prompt = f"""Create a professional character reference sheet for {cid} ({era} era, age {age}).

Character Description: {visual_anchor}

SHEET LAYOUT:
Arrange the sheet so that the left side contains two large full-body panels of the character in a relaxed A-pose with accurate anatomy and proportions and a clear silhouette: one full-body front view and one full-body back view, with consistent scale and alignment between them.

On the right side, create four portrait panels arranged in two rows: a front portrait with the face looking straight at the camera, a left-side portrait (profile or three-quarter view facing left), a right-side portrait (profile or three-quarter view facing right), and an extreme close-up face crop that clearly shows fine facial details such as eyes, eyelids or eyelashes, eyebrows, nose, mouth, skin or surface texture, and hair details.

CONSISTENCY RULES:
- Use a clean, neutral plain background so the character is clear
- Maintain perfect identity consistency across every panel so the character always looks like the same individual
- Keep the facial scale consistent across the three standard portraits
- Use even spacing and clean visual separation between all panels
- Lighting should remain consistent across the entire sheet (same direction, intensity, and softness)
- Controlled shadows that preserve detail without dramatic mood shifts
- Crisp, print-ready reference sheet with sharp details
- Do NOT change the style from the original description"""

                if style_desc:
                    prompt += f"\n\nVisual Style: {style_desc}"

                sheet_plan[sheet_key] = {
                    "character": cid,
                    "era": era,
                    "prompt": prompt,
                    "source_chapter": source_ch,
                    "target_chapters": chapters,
                    "freq": freq,
                }

        logger.info(f"📋 Sheet plan: {len(sheet_plan)} sheets to generate")

        # Generate sheets
        generated = 0
        for sheet_key, plan in sheet_plan.items():
            source_ch = plan["source_chapter"]
            cpm = self.proj.get_chapter_pm(source_ch)
            if not cpm:
                continue

            sheets_dir = os.path.join(cpm.root, "character_sheets")
            os.makedirs(sheets_dir, exist_ok=True)

            filename = f"{plan['character']}_{plan['era']}_x{plan['freq']}_ref.png"
            sheet_path = os.path.join(sheets_dir, filename)

            # Skip if already exists
            if os.path.exists(sheet_path) and os.path.getsize(sheet_path) > 1024:
                logger.info(f"⏭️ {sheet_key}: Already exists")
            else:
                logger.info(f"🎨 {sheet_key}: Generating sheet...")
                try:
                    result = await self.ai.generate_image(
                        prompt=plan["prompt"],
                        output_path=sheet_path,
                    )
                    if result:
                        logger.info(f"✅ {sheet_key}: Sheet saved → {sheet_path}")
                        generated += 1
                    else:
                        logger.warning(f"⚠️ {sheet_key}: Generation returned no result")
                        continue
                except Exception as e:
                    logger.warning(f"⚠️ {sheet_key}: Failed: {e}")
                    continue

            # Copy to target chapters
            for target_ch in plan["target_chapters"]:
                if target_ch == source_ch:
                    continue
                target_cpm = self.proj.get_chapter_pm(target_ch)
                if not target_cpm:
                    continue
                target_dir = os.path.join(target_cpm.root, "character_sheets")
                os.makedirs(target_dir, exist_ok=True)
                target_path = os.path.join(target_dir, filename)

                if not os.path.exists(target_path):
                    shutil.copy2(sheet_path, target_path)
                    logger.info(f"   📋 Copied to ch{target_ch:02d}")

        # Also generate metadata JSON per chapter
        self._save_chapter_metadata()

        logger.info(f"✅ Sheets complete: {generated} new sheets generated")

    def _save_chapter_metadata(self):
        """Save character_metadata.json for each chapter."""
        for ch in self.proj.get_all_chapters():
            idx = ch["index"]
            if idx == 0:
                continue

            cpm = self.proj.get_chapter_pm(idx)
            sheets_dir = os.path.join(cpm.root, "character_sheets")
            if not os.path.exists(sheets_dir):
                continue

            # Collect characters for this chapter
            metadata = {}
            for cid, data in self.timeline.items():
                ch_count = data.get("chapters", {}).get(str(idx), 0)
                if isinstance(data.get("chapters", {}), dict):
                    ch_count = data["chapters"].get(str(idx),
                                data["chapters"].get(idx, 0))
                if ch_count == 0:
                    continue

                # Find the current era for this chapter
                current_era = "single"
                visual_anchor = ""
                for phase in data.get("phases", []):
                    if idx in phase.get("chapters", []):
                        current_era = phase.get("era", "single")
                        visual_anchor = phase.get("visual_anchor", "")
                        break

                meta = self.char_db.get_json_metadata(cid.lower()) or {}
                meta["name"] = cid
                meta["scene_appearances"] = ch_count
                meta["era"] = current_era
                if visual_anchor:
                    meta["visual_anchor"] = visual_anchor
                metadata[cid] = meta

            if metadata:
                meta_path = os.path.join(sheets_dir, "character_metadata.json")
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------ #
    #  Step 4: Inject Visual Anchors into Scene Prompts
    # ------------------------------------------------------------------ #

    def inject_visual_anchors(self):
        """
        Update scene_prompts.txt for each chapter by injecting
        character visual descriptions inline.

        Before: "David stands before Goliath..."
        After:  "David (young shepherd boy with curly dark hair and olive skin
                 wearing a simple wool tunic) stands before Goliath
                 (towering warrior with dark bronze skin and thick black braided
                 beard wearing bronze scale armor)..."
        """
        logger.info("💉 Step 4: Injecting visual anchors into scene prompts...")

        if not self.visual_anchors:
            if os.path.exists(self.anchors_path):
                with open(self.anchors_path, "r", encoding="utf-8") as f:
                    self.visual_anchors = json.load(f)

        if not self.timeline:
            if os.path.exists(self.timeline_path):
                with open(self.timeline_path, "r", encoding="utf-8") as f:
                    self.timeline = json.load(f)

        updated_chapters = 0

        for ch in self.proj.get_all_chapters():
            idx = ch["index"]
            if idx == 0:
                continue

            cpm = self.proj.get_chapter_pm(idx)
            script_path = os.path.join(cpm.root, "script.json")
            if not os.path.exists(script_path):
                continue

            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)

            # Build visual anchor lookup for this chapter
            ch_anchors = {}  # char_name -> visual description
            for cid, anchor_data in self.visual_anchors.items():
                for phase in anchor_data.get("phases", []):
                    if idx in phase.get("chapters", []):
                        ch_anchors[cid] = phase.get("visual_anchor", "")
                        break

            if not ch_anchors:
                continue

            # Update each scene's objects field
            modified = False
            for scene in script.get("scenes", []):
                objects_text = scene.get("objects", "")
                for char_name, anchor_text in ch_anchors.items():
                    if not anchor_text:
                        continue

                    # Find character references in objects that DON'T already
                    # have a parenthetical description
                    # Pattern: "CharName" not followed by "("
                    pattern = rf'\b{re.escape(char_name)}\b(?!\s*\()'
                    if re.search(pattern, objects_text, re.IGNORECASE):
                        # Inject anchor as parenthetical
                        short_anchor = anchor_text[:120]  # Keep it manageable
                        replacement = f"{char_name} ({short_anchor})"
                        objects_text = re.sub(
                            pattern,
                            replacement,
                            objects_text,
                            count=1,
                            flags=re.IGNORECASE,
                        )
                        modified = True

                scene["objects"] = objects_text

            if modified:
                # Save updated script
                with open(script_path, "w", encoding="utf-8") as f:
                    json.dump(script, f, ensure_ascii=False, indent=2)

                # Regenerate prompts
                scenes = script.get("scenes", [])
                prompts_txt = format_scene_prompts_txt(scenes)

                sp1 = os.path.join(cpm.root, "scene_prompts.txt")
                with open(sp1, "w", encoding="utf-8") as f:
                    f.write(prompts_txt)

                sp2 = os.path.join(cpm.root, "scene_prompts2.txt")
                ScriptGenerator._save_single_line_prompts(prompts_txt, sp2)

                updated_chapters += 1
                logger.info(f"   ch{idx:02d}: Visual anchors injected")

        logger.info(f"✅ Visual anchors injected in {updated_chapters} chapters")

    # ------------------------------------------------------------------ #
    #  Main: Run All Steps
    # ------------------------------------------------------------------ #

    async def run(self):
        """Run the complete character management pipeline."""
        logger.info("🎭 ═══ Character Manager Pipeline ═══")
        logger.info(f"   Project: {self.proj.project_data.get('title', '')}")

        # Step 1: Timeline analysis
        self.analyze_timeline()

        # Step 2: Visual anchors
        await self.generate_visual_anchors()

        # Step 3: Character sheets
        await self.generate_sheets()

        # Step 4: Inject into prompts
        self.inject_visual_anchors()

        logger.info("✅ Character Manager Pipeline Complete!")
        logger.info(f"   📊 Timeline: {self.timeline_path}")
        logger.info(f"   🎨 Anchors: {self.anchors_path}")


# ---- CLI Entry Point ---- #

async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Character Manager for Bible Animation Projects"
    )
    parser.add_argument(
        "--project", type=str, required=True,
        help="Project slug (e.g., david_and_goliath)"
    )
    parser.add_argument(
        "--timeline-only", action="store_true",
        help="Only analyze timeline (no sheet generation)"
    )
    parser.add_argument(
        "--inject-only", action="store_true",
        help="Only inject visual anchors (assumes timeline + anchors exist)"
    )

    args = parser.parse_args()

    manager = CharacterManager(args.project)

    if args.timeline_only:
        manager.analyze_timeline()
    elif args.inject_only:
        manager.inject_visual_anchors()
    else:
        await manager.run()


if __name__ == "__main__":
    asyncio.run(main())
