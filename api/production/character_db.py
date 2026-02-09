"""
Character Database for Bible Animation.
Maintains consistent character appearances across episodes.

Character Consistency Techniques Applied:
1. Rare Name Anchoring — unique identifiers for latent space fixation
2. Uninterrupted Stream — no-comma identity descriptions to prevent attribute binding errors
3. Per-character negative guidance — drift prevention
"""

import json
import os
import logging
from typing import Optional

logger = logging.getLogger("character_db")

# Default characters for Bible animations
# Each character includes:
#   - Standard fields: id, name_ko, name_en, appearance, clothing, props, personality_traits
#   - Consistency fields: anchor_name, stream_description, negative_guidance
DEFAULT_CHARACTERS = [
    {
        "id": "moses",
        "name_ko": "모세",
        "name_en": "Moses",
        "anchor_name": "Moseth",
        "appearance": "An elderly man with a long white beard and deeply weathered, tanned skin. Intense, determined brown eyes. Tall and commanding presence.",
        "clothing": "A long, flowing dark brown robe with a woven rope belt. A draped tan cloak over his shoulders. Simple leather sandals.",
        "props": "A tall wooden shepherd's staff with a slightly curved top.",
        "personality_traits": "Humble yet authoritative, deeply faithful, reluctant leader who speaks with God.",
        "stream_description": "An elderly commanding man named Moseth with a long flowing white beard and deeply weathered sun-tanned skin and intense determined brown eyes standing tall with a powerful presence wearing a long flowing dark brown robe with a woven rope belt and a draped tan cloak over his broad shoulders clutching a tall wooden shepherd's staff with a curved top",
        "negative_guidance": "young face, short hair, clean shaven, modern clothing"
    },
    {
        "id": "abraham",
        "name_ko": "아브라함",
        "name_en": "Abraham",
        "anchor_name": "Abrahael",
        "appearance": "An aged man with a thick grey beard and kind, wise eyes. Weathered olive skin. Strong build despite his age.",
        "clothing": "Rich, dark blue and cream layered robes befitting a wealthy patriarch. A decorative headcloth held by a braided cord.",
        "props": "A walking stick. Sometimes carries a knife or torch.",
        "personality_traits": "Faithful, patient, hospitable, loving father figure.",
        "stream_description": "An aged wise patriarch named Abrahael with a thick grey beard and kind gentle eyes and weathered olive skin and a strong build despite his advanced years wearing rich dark blue and cream layered robes befitting a wealthy desert patriarch with a decorative headcloth held by a braided cord carrying a sturdy walking stick",
        "negative_guidance": "young face, modern clothing, skinny build"
    },
    {
        "id": "david",
        "name_ko": "다윗",
        "name_en": "David",
        "anchor_name": "Davith",
        "appearance": "A young man with short, curly reddish-brown hair and bright, courageous green eyes. Ruddy, handsome face with a strong jawline.",
        "clothing": "As a shepherd: simple beige tunic with a leather sling belt. As a king: rich purple and gold royal robes with a golden crown.",
        "props": "A leather sling and stones (as shepherd). A golden harp. A crown and sword (as king).",
        "personality_traits": "Brave, passionate, musical, deeply devoted to God, imperfect but repentant.",
        "stream_description": "A brave young shepherd boy named Davith with short curly reddish-brown hair and large bright green eyes full of courage and a ruddy sun-kissed handsome face with gentle freckles across his nose and a strong determined jawline wearing a simple cream-colored wool tunic cinched with a worn brown leather belt and carrying a small leather shepherd's sling and pouch of smooth river stones",
        "negative_guidance": "old face, long hair, crown, armor, grey beard, adult"
    },
    {
        "id": "goliath",
        "name_ko": "골리앗",
        "name_en": "Goliath",
        "anchor_name": "Goliathrak",
        "appearance": "A towering giant warrior, over 9 feet tall with a thick muscular build. A scarred, brutal face with cruel dark eyes and a heavy brow.",
        "clothing": "Full bronze armor — a massive bronze helmet, a coat of bronze scale armor, bronze greaves on his legs.",
        "props": "An enormous iron-tipped spear like a weaver's beam and a large bronze shield borne by a shield-bearer.",
        "personality_traits": "Arrogant, brutal, contemptuous, physically overwhelming.",
        "stream_description": "A towering menacing giant warrior named Goliathrak standing over nine feet tall with a massive hulking muscular build and a scarred brutish face with deep-set cruel dark eyes under a heavy furrowed brow and a broad flat nose wearing heavy ornate bronze scale armor with a massive bronze helmet and bronze greaves on his thick legs carrying an enormous iron-tipped spear thick as a weaver's beam",
        "negative_guidance": "small stature, friendly face, modern armor, thin build"
    },
    {
        "id": "jesus",
        "name_ko": "예수",
        "name_en": "Jesus",
        "anchor_name": "Yeshuael",
        "appearance": "A man in his early 30s with shoulder-length dark brown wavy hair and a short, well-groomed beard. Warm, compassionate brown eyes. Olive-toned skin. A calm, serene expression and gentle smile.",
        "clothing": "A simple, flowing white inner robe with a deep red or burgundy outer cloak draped over one shoulder. Brown leather sandals.",
        "props": "None typically. Sometimes a loaf of bread or a shepherd's crook in parables.",
        "personality_traits": "Compassionate, wise, authoritative yet gentle, loving, sacrificial.",
        "stream_description": "A serene man in his early thirties named Yeshuael with warm shoulder-length dark brown wavy hair and a short well-groomed beard and deeply compassionate warm brown eyes and olive-toned skin with a calm peaceful expression and gentle knowing smile wearing a simple flowing white inner robe with a deep red burgundy outer cloak draped over one shoulder and brown leather sandals",
        "negative_guidance": "angry expression, modern clothing, blond hair, blue eyes, old age"
    },
    {
        "id": "noah",
        "name_ko": "노아",
        "name_en": "Noah",
        "anchor_name": "Noahel",
        "appearance": "A very old man with a long, flowing white beard and deep wrinkles. Kind, weary but faithful eyes. Broad-shouldered and strong despite advanced age.",
        "clothing": "Rough-hewn, earth-toned robes in browns and greens. A thick leather apron when working on the ark.",
        "props": "Woodworking tools: a hammer, an adze. Plans or scrolls.",
        "personality_traits": "Righteous, obedient, patient, enduring ridicule with quiet faith.",
        "stream_description": "A very old broad-shouldered man named Noahel with a long flowing white beard and deep wrinkles and kind weary but faithful eyes and strong weathered hands despite his advanced age wearing rough-hewn earth-toned robes in browns and greens with a thick leather work apron and holding woodworking tools",
        "negative_guidance": "young face, clean shaven, modern tools, thin build"
    },
    {
        "id": "adam",
        "name_ko": "아담",
        "name_en": "Adam",
        "anchor_name": "Adamiel",
        "appearance": "A young, perfectly formed man with tan skin, dark brown hair, and dark eyes. Strong, muscular build. A face full of wonder and innocence.",
        "clothing": "Before the fall: simple coverings of light or leaves. After the fall: rough animal-skin garments.",
        "props": "None initially. Later, farming tools.",
        "personality_traits": "Curious, innocent, naming the animals, later ashamed and repentant.",
        "stream_description": "A young perfectly formed man named Adamiel with tan unblemished skin and dark brown hair and wide innocent dark eyes full of wonder and a strong muscular build and a face radiating pure innocence wearing simple natural coverings of broad green leaves",
        "negative_guidance": "old face, wrinkles, scars, modern clothing"
    },
    {
        "id": "eve",
        "name_ko": "하와",
        "name_en": "Eve",
        "anchor_name": "Evanel",
        "appearance": "A beautiful young woman with long, flowing dark hair and warm brown eyes. Olive skin, graceful features.",
        "clothing": "Before the fall: simple coverings of leaves or light. After the fall: rough animal-skin garments.",
        "props": "Flowers from the Garden. The forbidden fruit (a generic, beautiful glowing fruit—not specifically an apple).",
        "personality_traits": "Curious, nurturing, innocent, later sorrowful.",
        "stream_description": "A beautiful young woman named Evanel with long flowing dark hair and warm brown eyes and smooth olive skin and graceful delicate features and an expression of gentle curiosity wearing simple natural coverings of woven leaves and flowers",
        "negative_guidance": "old face, short hair, modern clothing, heavy makeup"
    },
    {
        "id": "joseph",
        "name_ko": "요셉",
        "name_en": "Joseph (son of Jacob)",
        "anchor_name": "Josephael",
        "appearance": "A handsome young man with clean-shaven face, dark hair, and bright, intelligent dark eyes. Later, Egyptian-styled appearance.",
        "clothing": "As a youth: a vibrant, multicolored coat. In Egypt: white Egyptian linen robes with gold accents, a gold collar necklace.",
        "props": "The coat of many colors. Egyptian signet ring. A golden goblet.",
        "personality_traits": "Dreamer, forgiving, wise administrator, emotional and loving toward family.",
        "stream_description": "A handsome young man named Josephael with a clean-shaven face and dark hair and bright intelligent dark eyes and an open trusting expression wearing a vibrant multicolored coat of many brilliant hues that catches the light beautifully",
        "negative_guidance": "old face, beard, plain clothing, dull colors"
    },
    {
        "id": "mary",
        "name_ko": "마리아",
        "name_en": "Mary (mother of Jesus)",
        "anchor_name": "Mirael",
        "appearance": "A young woman (teenager at annunciation) with a gentle, serene face. Dark brown hair partially covered. Modest, humble beauty. Later, a mature, sorrowful mother.",
        "clothing": "A simple blue veil/head covering over a light beige or white inner dress. Later, deeper blue robes.",
        "props": "A water jug. Baby Jesus swaddled in cloth.",
        "personality_traits": "Humble, obedient, contemplative, a treasuring heart, courageous faith.",
        "stream_description": "A young woman named Mirael with a gentle serene face and dark brown hair partially covered by a soft blue veil and modest humble beauty and warm compassionate eyes wearing a simple blue head covering over a light beige inner dress with a quiet peaceful expression",
        "negative_guidance": "old face, heavy makeup, modern clothing, uncovered hair"
    },
    {
        "id": "paul",
        "name_ko": "바울",
        "name_en": "Paul (Apostle)",
        "anchor_name": "Pauleth",
        "appearance": "A short man with a balding head, a dark, bushy beard, and intense, piercing eyes. Scarred from beatings and stoning. A scholarly demeanor.",
        "clothing": "Simple traveler's robes in muted browns and greys. A traveling cloak. Sometimes in Roman chains.",
        "props": "Scrolls and writing instruments. Chains (when imprisoned). A tentmaker's needle.",
        "personality_traits": "Passionate, brilliant, tireless, deeply converted from persecutor to apostle.",
        "stream_description": "A short intense man named Pauleth with a balding head and a dark bushy beard and intense piercing eyes and visible scars on his arms and face from beatings and stoning and a scholarly focused demeanor wearing simple traveler's robes in muted browns and greys with a worn traveling cloak",
        "negative_guidance": "tall stature, full hair, young face, clean skin, modern clothing"
    },
]


class CharacterDB:
    """Manages Bible character data for consistent visual prompts."""

    def __init__(self, db_path: Optional[str] = None):
        from config.settings import BIBLE_CONFIG
        self.db_path = db_path or BIBLE_CONFIG["character_db_path"]
        self.characters = {}
        self._load_or_create()

    def _load_or_create(self):
        """Load character DB from file or create default."""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for ch in data:
                    # Migrate old entries: add consistency fields if missing
                    self._ensure_consistency_fields(ch)
                    self.characters[ch["id"]] = ch
                logger.info(f"✅ Loaded {len(self.characters)} characters from {self.db_path}")
                return
            except Exception as e:
                logger.warning(f"⚠️ Failed to load character DB: {e}. Recreating.")

        # Create default
        for ch in DEFAULT_CHARACTERS:
            self.characters[ch["id"]] = ch
        self._save()
        logger.info(f"✅ Created default character DB with {len(self.characters)} characters")

    def _ensure_consistency_fields(self, ch: dict):
        """Auto-populate consistency fields if missing (backward compatibility)."""
        if "anchor_name" not in ch:
            # Generate a rare anchor name from existing name
            base = ch.get("name_en", ch["id"]).split("(")[0].strip()
            ch["anchor_name"] = f"{base}ael"

        if "stream_description" not in ch:
            # Build stream from appearance + clothing (strip commas for uninterrupted flow)
            appearance = ch.get("appearance", "")
            clothing = ch.get("clothing", "")
            combined = f"{appearance} wearing {clothing}"
            # Replace commas with " and" for uninterrupted stream
            ch["stream_description"] = combined.replace(", ", " and ")

        if "negative_guidance" not in ch:
            ch["negative_guidance"] = "distorted face, asymmetric eyes, extra limbs, deformed hands"

    def _save(self):
        """Save character DB to file."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(list(self.characters.values()), f, ensure_ascii=False, indent=2)

    def get(self, character_id: str) -> Optional[dict]:
        """Get character by ID."""
        return self.characters.get(character_id)

    def find_by_name(self, name: str) -> Optional[dict]:
        """Find character by Korean or English name (case-insensitive)."""
        name_lower = name.lower().strip()
        for ch in self.characters.values():
            if (ch["name_ko"] == name or
                ch["name_en"].lower() == name_lower or
                ch["id"] == name_lower):
                return ch
        return None

    # ---- Standard Prompt Fragment (comma-separated, backward compatible) ----

    def get_prompt_fragment(self, character_id: str) -> str:
        """
        Generate a visual description fragment for embedding into image/video prompts.
        Uses standard comma-separated format.
        """
        ch = self.characters.get(character_id)
        if not ch:
            ch = self.find_by_name(character_id)
        if not ch:
            return f"A biblical character named {character_id}."

        return (
            f"{ch['name_en']} ({ch['name_ko']}): "
            f"{ch['appearance']} "
            f"Wearing {ch['clothing']}. "
            f"{ch['props']}."
        )

    # ---- Character Consistency Methods ----

    def get_anchor_name(self, character_id: str) -> str:
        """Get the rare-name anchor for latent space fixation."""
        ch = self.characters.get(character_id)
        if not ch:
            ch = self.find_by_name(character_id)
        if not ch:
            return character_id
        return ch.get("anchor_name", ch["name_en"])

    def get_stream_fragment(self, character_id: str) -> str:
        """
        Get the uninterrupted stream description for a character.
        Returns a single flowing phrase with no internal commas,
        preventing attribute binding errors in the text encoder.
        """
        ch = self.characters.get(character_id)
        if not ch:
            ch = self.find_by_name(character_id)
        if not ch:
            return f"A biblical character named {character_id}"
        return ch.get("stream_description", self.get_prompt_fragment(character_id))

    def get_negative_guidance(self, character_id: str) -> str:
        """Get per-character negative guidance keywords."""
        ch = self.characters.get(character_id)
        if not ch:
            ch = self.find_by_name(character_id)
        if not ch:
            return ""
        return ch.get("negative_guidance", "")

    def get_all_prompt_fragments(self, character_ids: list) -> str:
        """Generate prompt fragments for multiple characters."""
        fragments = []
        for cid in character_ids:
            frag = self.get_prompt_fragment(cid)
            fragments.append(frag)
        return "\n".join(fragments)

    def get_all_stream_fragments(self, character_ids: list) -> str:
        """Generate uninterrupted stream fragments for multiple characters."""
        fragments = []
        for cid in character_ids:
            frag = self.get_stream_fragment(cid)
            fragments.append(frag)
        return "\n\n".join(fragments)

    def get_character_bible_markdown(self, character_ids: list) -> str:
        """
        Generate a structured Character Bible in Markdown format.
        Used to inject into LLM system prompts for consistent prompt generation.
        """
        sections = []
        for cid in character_ids:
            ch = self.characters.get(cid)
            if not ch:
                ch = self.find_by_name(cid)
            if not ch:
                continue

            section = f"""## {ch['name_en']} ({ch['name_ko']})
- **Anchor Name**: {ch.get('anchor_name', ch['name_en'])}
- **Identity**: {ch['appearance']}
- **Attire**: {ch['clothing']}
- **Props**: {ch['props']}
- **Personality**: {ch['personality_traits']}
- **Stream Description**: {ch.get('stream_description', 'N/A')}
- **Constraints (Negative)**: {ch.get('negative_guidance', 'N/A')}"""
            sections.append(section)

        return "\n\n".join(sections)

    def get_json_metadata(self, character_id: str) -> dict:
        """
        Generate structured JSON metadata for Veo 3.1 character locking.
        Follows the Gemini Gem Image Analysis Specialist schema for
        precise character identity preservation across scenes.
        """
        ch = self.characters.get(character_id)
        if not ch:
            ch = self.find_by_name(character_id)
        if not ch:
            return {"name": character_id}

        # Parse structured fields from appearance/clothing text
        hair_info = self._parse_hair(ch["appearance"])
        clothing_info = self._parse_clothing(ch["clothing"])
        age_info = self._extract_age(ch["appearance"])

        return {
            "name": ch.get("anchor_name", ch["name_en"]),
            "age": age_info,
            "gender": self._extract_gender(ch["appearance"]),
            "ethnicity": "Middle Eastern / Biblical",
            "skin_tone": self._extract_skin_tone(ch["appearance"]),
            "hair": hair_info,
            "clothing": clothing_info,
            "pose": "natural standing",
            "facial_expression": self._extract_expression(ch.get("personality_traits", "")),
            "accessories": self._extract_list_field(ch.get("props", "")),
            "held_objects": [],
            "emotions": self._extract_list_field(ch.get("personality_traits", "")),
            "body_language": "confident" if "brave" in ch.get("personality_traits", "").lower() else "calm",
            "stream_description": ch.get("stream_description", ""),
            "constraints": {
                "negative": ch.get("negative_guidance", ""),
                "must_include": ch.get("anchor_name", ch["name_en"]),
            },
        }

    def _parse_hair(self, appearance: str) -> dict:
        """Extract hair attributes from appearance text."""
        hair = {"style": "natural", "color": "dark"}
        app_lower = appearance.lower()
        # Color
        for color in ["white", "grey", "gray", "dark brown", "reddish-brown", "brown", "dark", "black", "red"]:
            if color in app_lower:
                hair["color"] = color
                break
        # Style
        for style in ["long flowing", "long", "short curly", "curly", "wavy", "shoulder-length", "balding", "flowing"]:
            if style in app_lower:
                hair["style"] = style
                break
        # Extras
        if "beard" in app_lower:
            hair["beard"] = True
            for b in ["long white beard", "thick grey beard", "dark bushy beard", "short well-groomed beard", "short beard"]:
                if b in app_lower:
                    hair["beard_description"] = b
                    break
        return hair

    def _parse_clothing(self, clothing: str) -> dict:
        """Extract clothing structure from text."""
        result = {
            "head": "",
            "torso": "",
            "legs": "",
            "feet": "",
            "materials": [],
        }
        cloth_lower = clothing.lower()
        # Head
        for h in ["helmet", "crown", "headcloth", "head covering", "veil"]:
            if h in cloth_lower:
                result["head"] = h
                break
        # Feet
        for f in ["sandals", "boots", "greaves"]:
            if f in cloth_lower:
                result["feet"] = f
                break
        # Materials
        for m in ["bronze", "leather", "wool", "linen", "gold", "iron", "animal-skin", "silk"]:
            if m in cloth_lower:
                result["materials"].append(m)
        # Torso is the main description
        result["torso"] = clothing.split(".")[0] if "." in clothing else clothing
        return result

    def _extract_age(self, appearance: str) -> str:
        """Extract approximate age from appearance description."""
        app_lower = appearance.lower()
        if "boy" in app_lower or "teenager" in app_lower:
            return "teenager"
        elif "young" in app_lower:
            return "young adult"
        elif "very old" in app_lower:
            return "very old"
        elif "elderly" in app_lower or "old" in app_lower or "aged" in app_lower:
            return "elderly"
        elif "30s" in app_lower or "early 30" in app_lower:
            return "early 30s"
        return "adult"

    def _extract_gender(self, appearance: str) -> str:
        app_lower = appearance.lower()
        if "woman" in app_lower or "girl" in app_lower:
            return "female"
        return "male"

    def _extract_skin_tone(self, appearance: str) -> str:
        app_lower = appearance.lower()
        for tone in ["olive-toned", "olive", "tanned", "sun-kissed", "ruddy", "tan", "weathered"]:
            if tone in app_lower:
                return tone
        return "olive"

    def _extract_expression(self, traits: str) -> str:
        traits_lower = traits.lower()
        if "compassionate" in traits_lower or "gentle" in traits_lower:
            return "gentle and compassionate"
        elif "brave" in traits_lower or "courageous" in traits_lower:
            return "determined and courageous"
        elif "arrogant" in traits_lower or "brutal" in traits_lower:
            return "sneering and contemptuous"
        elif "humble" in traits_lower:
            return "humble and serene"
        elif "passionate" in traits_lower:
            return "intense and passionate"
        return "calm"

    def _extract_list_field(self, text: str) -> list:
        """Extract a comma-separated text into a list."""
        if not text:
            return []
        return [item.strip() for item in text.split(",") if item.strip()][:5]

    def add_character(self, character: dict):
        """Add or update a character in the DB."""
        self._ensure_consistency_fields(character)
        self.characters[character["id"]] = character
        self._save()
        logger.info(f"✅ Added/Updated character: {character['id']}")

    def list_all(self) -> list:
        """List all character IDs and names."""
        return [(ch["id"], ch["name_ko"], ch["name_en"])
                for ch in self.characters.values()]

    def get_character_sheet_prompt(self, character_id: str) -> str:
        """
        Generate a 360° character reference sheet prompt for image generation.
        Based on the Gemini Gem workflow: create a multi-angle reference sheet
        that can then be analyzed by Gemini to extract precise JSON metadata.

        This is Step 1 of the character consistency pipeline:
        1. Generate character sheet (this method)
        2. Analyze with Gemini Gem → extract JSON metadata
        3. Use metadata in scene prompts for Veo 3.1
        """
        ch = self.characters.get(character_id)
        if not ch:
            ch = self.find_by_name(character_id)
        if not ch:
            return f"Character reference sheet for {character_id}"

        anchor = ch.get("anchor_name", ch["name_en"])
        stream = ch.get("stream_description", ch["appearance"])

        return f"""Create a professional character reference sheet for {anchor}.

Character Description: {stream}

Clothing: {ch['clothing']}
Props: {ch.get('props', 'None')}

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

    def copy_to_run(self, run_db_path: str):
        """Copy the character DB to a specific run directory for reproducibility."""
        import shutil
        os.makedirs(os.path.dirname(run_db_path), exist_ok=True)
        shutil.copy2(self.db_path, run_db_path)
        logger.info(f"📋 Character DB copied to {run_db_path}")
