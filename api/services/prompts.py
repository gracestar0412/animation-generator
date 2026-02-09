"""
Bible Animation Prompt Templates.
System prompt and segment generation for Bible storytelling.
Includes character consistency techniques from Gemini Gem / Veo 3.1 workflow.
"""

import json

SYSTEM_PROMPT = """
[SYSTEM]
You are an expert Bible Animation scriptwriter and director.
Your goal is to create compelling, faithful Bible animation scripts
that are both narratively engaging and visually stunning.

CRITICAL RULES:
1. Faithfulness: Stay true to the biblical text while making it dramatically engaging.
2. Visual Clarity: Each scene must have a clear, specific visual description.
3. Character Consistency: Always describe characters using the provided character descriptions.
   - Use the CHARACTER BIBLE anchor names in every scene
   - Use uninterrupted stream descriptions (no commas within identity blocks)
   - Include negative guidance to prevent visual drift
4. Pacing: Mix dramatic moments with quiet, contemplative beats.
5. Duration: Each scene narration should match its specified duration.
6. Tone: Reverent yet dramatic. Not preachy—let the story speak.
7. Video Prompts: Must follow the structured format (Objects/Action/Style/Camera/Atmosphere/SFX/Negative).
8. Output: MUST follow JSON Schema exactly.
"""


def get_bible_planning_prompt(book: str, chapter: str, context: str = "") -> str:
    return f"""
    [USER]
    Bible Book: {book}
    Chapter/Verses: {chapter}
    Additional Context: {context}
    
    Goal: Plan the episode structure for a Bible animation video.
    Target Audience: Korean-speaking Christians and general audience
    Tone: Reverent + Cinematic + Emotionally moving
    Duration: 10 minutes (600 seconds)
    
    Output Format (JSON):
    {{
      "episode": {{
        "title_ko": "한국어 에피소드 제목",
        "title_en": "English Episode Title",
        "book": "{book}",
        "chapter": "{chapter}",
        "summary": "2-3 sentence summary of this episode",
        "key_characters": ["character_id_1", "character_id_2"],
        "act_structure": [
          {{
            "act": 1,
            "title": "Act title",
            "description": "What happens in this act",
            "duration_sec": 120,
            "key_moments": ["moment 1", "moment 2"]
          }}
        ],
        "emotional_arc": "Description of emotional journey",
        "visual_themes": ["desert landscape", "divine light", "ancient architecture"]
      }}
    }}
    """


def get_bible_script_prompt(
    plan: dict,
    character_descriptions: str,
    segment_idx: int = 1,
    prev_context: str = "",
    target_seconds: int = 120,
    scene_budget: str = "",
) -> str:
    budget_section = ""
    if scene_budget:
        budget_section = f"""
    SCENE BUDGET (YOU MUST FOLLOW THIS ALLOCATION):
    {scene_budget}
    
    The above scene budget specifies how many scenes and seconds to allocate to each story event.
    Events marked [CLIMAX] are the dramatic peak — they MUST receive AT LEAST the allocated scenes.
    Do NOT compress climax events. If you run short on time, compress earlier non-climax events instead.
    Lines marked [MUST-INCLUDE] contain key scripture quotes that MUST appear as narration or dialogue.
    """

    return f"""
    [USER]
    You are writing a detailed scene-by-scene script for a Bible animation episode.
    
    Episode Plan:
    {plan}
    
    CHARACTER BIBLE (MUST use these descriptions exactly for consistency):
    {character_descriptions}
    
    Current Segment: {segment_idx}
    Previous Context: {prev_context}
    {budget_section}
    INSTRUCTION:
    Write the next {target_seconds} seconds of the script.
    
    For each scene, provide:
    1. "narration" - Narration text (dramatic, reverent storytelling)
    2. "duration" - Scene duration in seconds (5-8s MAX — Veo video generation limit is 8 seconds!)
    3. "characters" - List of character IDs appearing in this scene
    4. "video_prompt" - Structured video generation prompt with these fields:
       - Objects: Physical items and characters (use ANCHOR NAMES and uninterrupted stream descriptions!)
       - Action: What happens, movements, gestures
       - Style: Visual style (will be overridden by style preset)
       - Camera: Shot type and movement
       - Atmosphere: Mood and environment description
       - SFX: Sound effects description
       - Negative: What to avoid (visual drift prevention)
    
    Format (Strict JSON List):
    [
      {{
        "narration": "The story begins...",
        "duration": 8,
        "characters": ["moses"],
        "video_prompt": {{
          "objects": "[Character stream description]. [Scene elements].",
          "action": "Moses raises his staff...",
          "style": "Cinematic biblical animation...",
          "camera": "Low-angle wide shot...",
          "atmosphere": "Awe-inspiring and dramatic...",
          "sfx": "Deep rumbling of the earth...",
          "negative": "distorted face, extra limbs..."
        }}
      }}
    ]
    
    CRITICAL REMINDERS:
    - MAXIMUM 8 SECONDS PER SCENE. Each scene's narration must be speakable in under 8 seconds (~15-20 words max). This is a hard constraint from Veo video generation.
    - For a {target_seconds}-second segment, you need approximately {target_seconds}//7 scenes (averaging 7 seconds each).
    - In "objects", ALWAYS use the full CHARACTER BIBLE stream descriptions.
    - Use anchor names (the unique names) to lock character identity.
    - Keep narration natural and dramatic.
    - Each scene should be self-contained visually.
    - Vary camera angles and shot types for visual interest.
    
    SCENE DISTRIBUTION RULES:
    - CLIMAX scenes are the dramatic peak that viewers are waiting for. NEVER compress them.
    - Main characters (protagonists) should have proportionally MORE screen time.
    - Key biblical quotes and declarations MUST appear as narration — these are the spiritual core.
    - If running out of time, compress setup/transition scenes, NEVER climax or key dialogue.
    - Dialogue-heavy events (persuasion, argument) should be CONCISE — focus on the most impactful lines.
    - Action events (battles, miracles) should be EXPANDED with multiple camera angles and dramatic pacing.
    """


def format_scene_prompts_txt(scenes: list) -> str:
    """
    Format scenes into scene_prompts.txt for user to generate videos.
    Each scene is separated by a blank line.
    Includes all consistency fields: objects, action, style, camera, atmosphere, sfx, negative.
    """
    blocks = []
    for scene in scenes:
        vp = scene.get("video_prompt", {})
        if isinstance(vp, str):
            blocks.append(f"Scene {scene.get('id', '?')}:\n{vp}")
            continue

        # Case-insensitive getter for video_prompt fields
        def _get(key):
            return vp.get(key) or vp.get(key.capitalize()) or vp.get(key.lower()) or ""

        lines = [f"Scene {scene.get('id', '?')}:"]
        if _get("objects"):
            lines.append(f"Objects: {_get('objects')}")
        if _get("action"):
            lines.append(f"Action: {_get('action')}")
        if _get("style"):
            lines.append(f"Style: {_get('style')}")
        if _get("camera"):
            lines.append(f"Camera: {_get('camera')}")
        if _get("atmosphere"):
            lines.append(f"Atmosphere: {_get('atmosphere')}")
        if _get("sfx"):
            lines.append(f"SFX: {_get('sfx')}")
        if _get("negative"):
            lines.append(f"Negative: {_get('negative')}")

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + "\n"


def format_scene_prompts_json(scenes: list, character_db=None) -> str:
    """
    Format scenes into JSON-structured prompts for Veo 3.1 character locking.
    Based on the Gemini Gem workflow: precise JSON metadata for each scene.
    """
    output = []
    for scene in scenes:
        vp = scene.get("video_prompt", {})
        if isinstance(vp, str):
            output.append({"scene_id": scene.get("id"), "prompt": vp})
            continue

        scene_json = {
            "scene_id": scene.get("id"),
            "narration": scene.get("narration", ""),
            "duration": scene.get("tts_duration", scene.get("duration", 8)),
            "prompt": {
                "objects": vp.get("objects", ""),
                "action": vp.get("action", ""),
                "style": vp.get("style", ""),
                "camera": vp.get("camera", ""),
                "atmosphere": vp.get("atmosphere", ""),
                "sfx": vp.get("sfx", ""),
            },
            "negative": vp.get("negative", ""),
        }

        # Add character JSON metadata if character_db is available
        chars = scene.get("characters", [])
        if character_db and chars:
            scene_json["characters"] = {}
            for cid in chars:
                meta = character_db.get_json_metadata(cid)
                if meta:
                    scene_json["characters"][cid] = meta

        output.append(scene_json)

    return json.dumps(output, ensure_ascii=False, indent=2)
