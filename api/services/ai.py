"""
AI Client for Bible Animation Generator.
Uses Google Vertex AI (Gemini) for script generation.
"""

import logging
import random
import os
import json
import asyncio
from typing import Optional

logger = logging.getLogger("ai_service")


class AIClient:
    def __init__(self):
        self.model_name = "gemini-3-flash-preview"
        self.client = None
        self.project_id = os.getenv("PROJECT_ID", "")
        self.credentials_path = os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS",
            os.path.join(os.getcwd(), "shorts.json")
        )

        if os.path.exists(self.credentials_path):
            try:
                from google import genai

                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path
                self.client = genai.Client(
                    vertexai=True,
                    project=self.project_id,
                    location="global"
                )
                logger.info(f"AIClient initialized with Vertex AI: {self.credentials_path}")
            except ImportError:
                logger.warning("google-genai library not found.")
            except Exception as e:
                logger.error(f"Failed to initialize GenAI client: {e}")
        else:
            logger.warning(f"Credentials not found: {self.credentials_path}")

    # ---- Retry Logic ----

    async def _retry_call(self, func, *args, max_retries: int = 5, **kwargs):
        """Retry with exponential backoff for quota/server errors."""
        base_wait = 5.0

        for attempt in range(max_retries):
            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    return await result
                return result
            except Exception as e:
                error_msg = str(e)
                is_retryable = any(x in error_msg for x in
                                   ["429", "RESOURCE_EXHAUSTED", "503", "Service Unavailable"])

                if is_retryable and attempt < max_retries - 1:
                    wait_time = (base_wait * (2 ** attempt)) + (random.random() * 2)
                    logger.warning(
                        f"⏳ API Error. Retrying in {wait_time:.1f}s "
                        f"(Attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    raise

    # ---- Bible Script Generation ----

    async def generate_bible_plan(self, book: str, chapter: str, context: str = "") -> dict:
        """Generate episode planning structure."""
        if not self.client:
            return self._fallback_plan(book, chapter)

        from api.services.prompts import SYSTEM_PROMPT, get_bible_planning_prompt
        from google.genai import types

        logger.info(f"🧠 Planning episode: {book} {chapter}")
        prompt = get_bible_planning_prompt(book, chapter, context)

        config = types.GenerateContentConfig(
            temperature=0.8,
            response_mime_type="application/json",
            system_instruction=SYSTEM_PROMPT,
        )

        async def _call():
            return await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=prompt,
                config=config,
            )

        response = await self._retry_call(_call)

        try:
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Failed to parse plan: {e}")
            return self._fallback_plan(book, chapter)

    async def generate_bible_script(
        self,
        plan: dict,
        character_descriptions: str,
        target_duration_minutes: float = 10.0,
        scene_budget: str = "",
    ) -> list:
        """
        Generate scene-by-scene script with video prompts.
        Generates in segments to handle long content.
        scene_budget: pre-formatted budget allocation string from key_events weights.
        """
        if not self.client:
            return self._fallback_script()

        from api.services.prompts import SYSTEM_PROMPT, get_bible_script_prompt
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=0.8,
            response_mime_type="application/json",
            system_instruction=SYSTEM_PROMPT,
        )

        target_seconds = target_duration_minutes * 60
        current_seconds = 0
        all_scenes = []
        segment_idx = 1
        prev_context = ""

        while current_seconds < target_seconds:
            remaining = target_seconds - current_seconds
            segment_dur = min(120, remaining)

            logger.info(
                f"📝 Segment {segment_idx} "
                f"({current_seconds:.0f}s / {target_seconds:.0f}s)"
            )

            prompt = get_bible_script_prompt(
                plan=json.dumps(plan, ensure_ascii=False),
                character_descriptions=character_descriptions,
                segment_idx=segment_idx,
                prev_context=prev_context,
                target_seconds=int(segment_dur),
                scene_budget=scene_budget,
            )

            try:
                async def _call():
                    return await asyncio.to_thread(
                        self.client.models.generate_content,
                        model=self.model_name,
                        contents=prompt,
                        config=config,
                    )

                response = await self._retry_call(_call)
                segment_scenes = json.loads(response.text)

                # Assign sequential IDs
                for s in segment_scenes:
                    s["id"] = len(all_scenes) + 1
                    all_scenes.append(s)
                    current_seconds += s.get("duration", 8)

                # Update context for next segment
                if segment_scenes:
                    last = segment_scenes[-1]
                    prev_context += (
                        f"\nSegment {segment_idx} ended with: "
                        f"{last.get('narration', '')[:100]}"
                    )

                segment_idx += 1

                if len(all_scenes) > 80:
                    logger.warning("⚠️ Scene cap reached (80)")
                    break

            except Exception as e:
                logger.error(f"Failed to generate segment {segment_idx}: {e}")
                break

        logger.info(f"✅ Generated {len(all_scenes)} scenes ({current_seconds:.0f}s)")
        return all_scenes

    async def refine_script(self, scenes: list, character_descriptions: str) -> list:
        """
        Quality check: verify character consistency and narration quality.
        """
        if not self.client or not scenes:
            return scenes

        from google.genai import types
        import re

        logger.info("🔍 Script quality verification...")

        # Extract a subset for verification (first 5, last 5, every 10th)
        sample_indices = set(range(min(5, len(scenes))))
        sample_indices.update(range(max(0, len(scenes) - 5), len(scenes)))
        sample_indices.update(range(0, len(scenes), 10))
        sample_scenes = [scenes[i] for i in sorted(sample_indices) if i < len(scenes)]

        prompt = f"""
        Review these Bible animation scenes for quality:
        
        Character References:
        {character_descriptions}
        
        Scenes to Review:
        {json.dumps(sample_scenes, ensure_ascii=False, indent=2)}
        
        Check for:
        1. Character description consistency (do scene prompts match the reference descriptions?)
        2. Narration quality (natural Korean, appropriate tone)
        3. Visual clarity (can each scene be independently produced?)
        
        Return a JSON object:
        {{
          "issues": [
            {{"scene_id": 1, "type": "character_mismatch", "detail": "설명"}}
          ],
          "overall_quality": "good/needs_work",
          "suggestions": ["suggestion 1"]
        }}
        """

        config = types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
        )

        try:
            async def _call():
                return await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )

            response = await self._retry_call(_call)
            review = json.loads(response.text)

            issues = review.get("issues", [])
            if issues:
                logger.warning(f"⚠️ {len(issues)} quality issues found")
                for issue in issues[:5]:
                    logger.warning(f"  Scene {issue.get('scene_id')}: {issue.get('detail')}")
            else:
                logger.info("✅ Script quality check passed")

        except Exception as e:
            logger.warning(f"Script review failed (non-fatal): {e}")

        return scenes

    async def generate_metadata(self, script: dict, plan: dict) -> dict:
        """Generate YouTube metadata (titles, description, hashtags)."""
        if not self.client:
            return self._fallback_metadata(plan)

        from google.genai import types

        episode = plan.get("episode", {})
        all_narrations = " ".join(
            s.get("narration", "") for s in script.get("scenes", [])
        )[:2000]

        prompt = f"""
        Generate YouTube metadata for a Bible animation video.
        
        Episode: {episode.get("title_ko", "성경 애니메이션")}
        Book: {episode.get("book", "")} {episode.get("chapter", "")}
        Summary: {episode.get("summary", "")}
        
        Script excerpt: {all_narrations}
        
        Return JSON:
        {{
          "titles": [
            "한국어 제목 1 (hooks viewers)",
            "한국어 제목 2",
            "한국어 제목 3"
          ],
          "description": "YouTube description in Korean (300-500 chars)",
          "hashtags": ["#성경", "#애니메이션", "..."],
          "tags": ["keyword1", "keyword2", "..."]
        }}
        """

        config = types.GenerateContentConfig(
            temperature=0.8,
            response_mime_type="application/json",
        )

        try:
            async def _call():
                return await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )

            response = await self._retry_call(_call)
            return json.loads(response.text)

        except Exception as e:
            logger.error(f"Metadata generation failed: {e}")
            return self._fallback_metadata(plan)

    # ---- Project (Long-Form) Methods ----

    async def plan_chapters(
        self,
        title: str,
        scripture_ref: str,
        language: str = "en",
    ) -> list[dict]:
        """
        Use AI to plan chapter breakdown for a long-form Bible animation.
        Returns a list of chapter dicts with title, slug, duration_target, etc.
        """
        from google.genai import types

        lang_label = "English" if language == "en" else "Korean" if language == "ko" else language

        prompt = f"""
You are planning a long-form animated Bible movie. Break the story into chapters.

Title: {title}
Scripture: {scripture_ref}
Language: {lang_label}

Rules:
1. ALWAYS start with an "Introduction" chapter (ch00) — hooks the viewer with a dramatic overview of the full story, ends with a call-to-action (subscribe/like/notification)
2. ALWAYS end with an "Outro" chapter — summarizes lessons learned, ends with a final call-to-action
3. The TOTAL duration of all chapters combined should be 25–35 minutes
4. Each chapter should be 1.5–3.5 minutes long
5. Each chapter covers a self-contained narrative arc
6. The number of chapters depends on the story length (typically 8–15 chapters)
7. Chapter titles should be dramatic and evocative

Return JSON array:
[
  {{
    "title": "Introduction",
    "slug": "introduction",
    "duration_target": "1m30s",
    "key_events": "Dramatic hook, story overview, subscribe CTA",
    "scripture_range": ""
  }},
  {{
    "title": "The Forgotten Son",
    "slug": "the_forgotten_son",
    "duration_target": "2m20s",
    "key_events": "Samuel anoints David secretly",
    "scripture_range": "1 Samuel 16:1-13"
  }},
  ...
  {{
    "title": "Outro",
    "slug": "outro",
    "duration_target": "2m30s",
    "key_events": "Lessons learned, final CTA",
    "scripture_range": ""
  }}
]
"""

        config = types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json",
        )

        try:
            async def _call():
                return await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )

            response = await self._retry_call(_call)
            chapters = json.loads(response.text)
            logger.info(f"📋 AI planned {len(chapters)} chapters")
            return chapters

        except Exception as e:
            logger.error(f"Chapter planning failed: {e}")
            # Fallback: basic 3-chapter structure
            return [
                {"title": "Introduction", "slug": "introduction",
                 "duration_target": "1m30s", "key_events": "Story hook, CTA"},
                {"title": title, "slug": title.lower().replace(" ", "_")[:30],
                 "duration_target": "5m", "key_events": "Main story"},
                {"title": "Outro", "slug": "outro",
                 "duration_target": "2m", "key_events": "Lessons, CTA"},
            ]

    async def generate_project_metadata(
        self,
        project_data: dict,
        timestamps: list[dict],
    ) -> dict:
        """
        Generate Ark Films-style YouTube metadata for a complete project.
        Includes chapter timestamps, Bible verses, and structured description.
        """
        from google.genai import types

        # Format timestamps
        ts_text = "\n".join(
            f"{t['timestamp']} {t['title']}" for t in timestamps
        )

        prompt = f"""
Generate YouTube metadata for a long-form animated Bible movie.
Follow the style of professional Bible animation channels like Ark Films.

Project: {project_data.get('title', '')}
Scripture: {project_data.get('scripture_ref', '')}
Language: {project_data.get('language', 'en')}

Chapter timestamps:
{ts_text}

Return JSON with this EXACT structure:
{{
  "title": "Main Title: Subtitle | Stunning 3D Animated Movie",
  "alt_titles": ["Alt title 1", "Alt title 2"],
  "description_header": "Full Movie | 3D Animated Bible Story | From [start] to [end]",
  "description_hook": "A compelling 2-3 sentence summary paragraph",
  "what_youll_discover": "🎬 WHAT YOU'LL DISCOVER IN THIS MOVIE:\\n(detailed paragraph)",
  "chapters_section": "📖 CHAPTERS\\n{ts_text}",
  "key_bible_verses": [
    {{"verse": "actual text", "reference": "Book Chapter:Verse"}}
  ],
  "scripture_reference": "📚 SCRIPTURE REFERENCE\\nThis animated movie is based on ...",
  "cta": "If this video blessed you, please LIKE 👍, COMMENT 💬, and SUBSCRIBE 🔔 to support our channel!",
  "hashtags": ["#tag1", "#tag2", "..."],
  "tags": ["keyword1", "keyword2", "..."]
}}

Generate 20+ hashtags and 20+ tags. Make everything engaging and SEO-optimized.

=== YouTube SEO Best Practices (MUST FOLLOW) ===
TITLE: Use action/journey phrasing ("From Shepherd to King"), include "Full Movie" or "3D Animated", under 70 chars, most searchable keyword first.
DESCRIPTION: ALWAYS include "Bible Stories for Kids and Adults" in subtitle for search breadth. Include hook paragraph, WHAT YOU'LL DISCOVER section, CHAPTERS timestamps, KEY BIBLE VERSES (2-3 actual verses), SCRIPTURE REFERENCE, and CTA.
HASHTAGS (critical): Only include hashtags DIRECTLY relevant to the story. DO NOT add character names or themes absent from the story (e.g., no #Jesus if Jesus isn't in the story). Include format (#3danimation #animatedbiblemovie), audience (#biblestoriesforkids #sundayschool), trending (#faithoverfear) tags. 15-25 total, all lowercase.
TAGS: Include both short and long-tail keywords, including "Bible Stories for Kids", "Bible Stories for Adults", "Full Movie".
"""

        config = types.GenerateContentConfig(
            temperature=0.8,
            response_mime_type="application/json",
        )

        try:
            async def _call():
                return await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )

            response = await self._retry_call(_call)
            return json.loads(response.text)

        except Exception as e:
            logger.error(f"Project metadata generation failed: {e}")
            return {
                "title": project_data.get("title", "Bible Animation"),
                "description": f"Based on {project_data.get('scripture_ref', '')}",
                "chapters_section": f"📖 CHAPTERS\n{ts_text}",
                "hashtags": ["#bible", "#animation"],
                "tags": ["bible", "animation"],
            }

    # ---- Image Generation ----

    async def generate_image(self, prompt: str, output_path: str) -> bool:
        """
        Generate a character reference sheet image using Vertex AI Imagen.
        Saves the image to output_path as PNG.
        """
        if not self.client:
            logger.warning("⚠️ No AI client, cannot generate image")
            return False

        from google.genai import types

        logger.info(f"🎨 Generating image → {os.path.basename(output_path)}")

        try:
            async def _call():
                return await asyncio.to_thread(
                    self.client.models.generate_images,
                    model="imagen-3.0-generate-002",
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="1:1",
                        person_generation="ALLOW_ADULT",
                    ),
                )

            response = await self._retry_call(_call)

            if response and response.generated_images:
                image = response.generated_images[0]
                image.image.save(output_path)
                logger.info(f"✅ Image saved: {output_path}")
                return True
            else:
                logger.warning("⚠️ No image in response")
                return False

        except Exception as e:
            logger.warning(f"⚠️ Image generation failed: {e}")
            return False


    # ---- Visual Quality Analysis ----

    async def analyze_scene_quality(self, image_path: str, scene_context: str = "", video_prompt: str = "") -> dict:
        """
        Analyze a scene keyframe for visual quality issues using Gemini 3 Flash.
        Returns: {"status": "PASS"|"WARN"|"FAIL", "issues": [...], "score": 1-10}
        """
        if not self.client:
            logger.warning("⚠️ No AI client, cannot analyze quality")
            return {"status": "WARN", "issues": ["No AI client available"], "score": 5}

        from google.genai import types
        import base64

        if not os.path.exists(image_path):
            return {"status": "FAIL", "issues": [f"Image not found: {image_path}"], "score": 0}

        # Read image as base64
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        prompt = f"""You are a professional visual quality assurance inspector for 3D animated Bible videos 
(Pixar/Disney style). Analyze this frame and rate its quality.

**Narration**: {scene_context if scene_context else "Bible animation scene"}
**Video Prompt**: {video_prompt if video_prompt else "N/A"}

IMPORTANT CONTEXT: This is a Bible animation. Supernatural/miraculous elements are INTENTIONAL and should NOT be flagged as issues:
- Divine light beams, glowing halos, heavenly radiance = INTENTIONAL
- Parting waters, fire from heaven, angels appearing = INTENTIONAL  
- Oversized warriors (Goliath), dramatic weather = INTENTIONAL
- Oil/anointing flowing supernaturally = INTENTIONAL
Only flag ACTUAL AI generation defects, NOT narrative/story elements.

Check for these ACTUAL defects only:
1. **Anatomical distortion**: Extra/fused fingers, missing limbs, deformed faces, melted body parts
2. **Character quality**: Melted wax appearance, smeared facial features, broken geometry
3. **Visual artifacts**: Glitch textures, ghosting, obvious seams, color banding
4. **Broken physics**: Floating objects with no narrative reason, limbs detached from body
5. **Style break**: Photorealistic patches mixed with cartoon, severely inconsistent quality

Reply ONLY with a JSON object (no markdown):
{{"status": "PASS" or "WARN" or "FAIL", "score": 1-10, "issues": ["list of ACTUAL defects only"], "recommendation": "brief action recommendation"}}

- PASS (score 7-10): Scene is ready for production
- WARN (score 4-6): Minor defects, may be acceptable  
- FAIL (score 1-3): Severe defects, needs regeneration
"""

        try:
            image_part = types.Part.from_bytes(
                data=image_bytes,
                mime_type="image/jpeg"
            )

            config = types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            )

            async def _call():
                return await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=self.model_name,
                    contents=[image_part, prompt],
                    config=config,
                )

            response = await self._retry_call(_call)

            if response and response.text:
                result = json.loads(response.text)
                return result
            else:
                return {"status": "WARN", "issues": ["Empty response from AI"], "score": 5}

        except json.JSONDecodeError:
            # Try to extract JSON from response
            if response and response.text:
                logger.warning(f"⚠️ Non-JSON response: {response.text[:200]}")
            return {"status": "WARN", "issues": ["Could not parse AI response"], "score": 5}
        except Exception as e:
            logger.warning(f"⚠️ Quality analysis failed: {e}")
            return {"status": "WARN", "issues": [f"Analysis error: {str(e)}"], "score": 5}

    # ---- Fallbacks ----

    def _fallback_plan(self, book: str, chapter: str) -> dict:
        return {
            "episode": {
                "title_ko": f"{book} {chapter}",
                "title_en": f"{book} {chapter}",
                "book": book,
                "chapter": chapter,
                "summary": f"{book} {chapter} 이야기",
                "key_characters": [],
                "act_structure": [
                    {"act": 1, "title": "시작", "description": "이야기의 시작",
                     "duration_sec": 200, "key_moments": []},
                    {"act": 2, "title": "전개", "description": "이야기의 전개",
                     "duration_sec": 250, "key_moments": []},
                    {"act": 3, "title": "결말", "description": "이야기의 결말",
                     "duration_sec": 150, "key_moments": []},
                ],
                "emotional_arc": "Beginning → Crisis → Resolution",
                "visual_themes": ["biblical landscape", "ancient architecture"],
            }
        }

    def _fallback_script(self) -> list:
        return [
            {
                "id": 1,
                "narration": "태초에 하나님이 천지를 창조하셨습니다.",
                "duration": 5,
                "characters": [],
                "video_prompt": {
                    "objects": "A vast, formless void. Dark waters churning.",
                    "action": "Light begins to appear, slowly illuminating the darkness.",
                    "style": "Cinematic biblical animation with dramatic lighting.",
                    "camera": "Slow pull back from darkness into light.",
                    "atmosphere": "Awe-inspiring, primordial, the beginning of everything.",
                    "sfx": "Deep reverberating hum. A divine breath of wind.",
                },
            }
        ]

    def _fallback_metadata(self, plan: dict) -> dict:
        episode = plan.get("episode", {})
        title = episode.get("title_ko", "성경 애니메이션")
        return {
            "titles": [title],
            "description": f"{title} - 성경 애니메이션 에피소드",
            "hashtags": ["#성경", "#애니메이션", "#Bible"],
            "tags": ["성경", "애니메이션", "Bible"],
        }
