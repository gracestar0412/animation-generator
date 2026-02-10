# 📖 Bible Animation Generator

AI-powered production pipeline for Bible story animations. Automates script generation, TTS narration, character consistency, thumbnail creation, and video assembly for long-form chapter-based YouTube projects.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Production Pipeline                            │
│                                                                      │
│  Project Init ─→ Script + TTS ─→ QC ─→ Character Mgmt               │
│   (AI Plan)      (Gemini/Edge)  (Validate) (Timeline/Sheets)         │
│                                                                      │
│  ─→ [Veo Videos] ─→ Intro Assembly ─→ Render ─→ Merge               │
│      (Manual)       (Auto-match)      (FFmpeg)  (FFmpeg)             │
│                                                                      │
│  ─→ Shorts ─→ Thumbnails ─→ Metadata ─→ YouTube-Ready               │
│    (9:16)   (Imagen+Nano)   (Gemini)                                 │
└──────────────────────────────────────────────────────────────────────┘
```

### Key Features

- **AI Script Generation** — Gemini-powered scene-by-scene scripts with structured video prompts
- **Character Consistency** — Rare-name anchoring, stream descriptions, era-aware reference sheets, visual anchor injection
- **Multi-format Output** — 16:9 long-form chapters + 9:16 YouTube Shorts (full + curation)
- **Intro Auto-Assembly** — Reuses existing chapter scenes with semantic matching (narration + character + keyword similarity)
- **AI Thumbnail Pipeline** — Gemini concept generation → Imagen 3 backgrounds → Nano Banana Pro 3D metallic title compositing
- **AI Scene QC** — Gemini 3 Flash visual quality analysis of scene keyframes
- **CTA Overlay** — Automated green-screen subscribe/like overlay (16:9 only)
- **Audio Priority System** — Per-scene TTS / Veo original / mix blending modes
- **Multi-Language TTS** — English, Korean, Japanese, Chinese, Spanish (Edge-TTS)
- **Configurable Art Styles** — Pixar/Disney, Ark Films, Watercolor, Stained Glass presets

### AI Models Used

| Model | Purpose |
|-------|---------|
| **Gemini 3 Flash** (`gemini-3-flash-preview`) | Script generation, metadata, thumbnail concepts, scene QC |
| **Gemini 2.5 Flash** (`gemini-2.5-flash`) | VTT subtitle generation from audio |
| **Imagen 3** (`imagen-3.0-generate-002`) | Character sheets, thumbnail backgrounds |
| **Nano Banana Pro** (`gemini-3-pro-image-preview`) | 3D metallic title compositing on thumbnails |

## Requirements

- Python 3.10+
- FFmpeg (with libx264 and libfdk_aac)
- Google Cloud credentials (Vertex AI — Gemini + Imagen)

## Setup

```bash
# 1. Clone & enter
git clone git@github.com:gracestar0412/animation-generator.git
cd animation-generator

# 2. Virtual environment
python3 -m venv venv && source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
cp .env.example .env
# Edit .env: set GOOGLE_APPLICATION_CREDENTIALS and PROJECT_ID
# Place your GCP service account JSON key in the project root
```

## Quick Start

### 1. Create a Project

```bash
python -m api.production.project_manager create \
  --title "david_and_goliath" --scripture "1 Samuel 16-31"
```

Generates `project.json` with AI-planned chapter structure, `character_db.json`, and all chapter directories.

### 2. Generate Scripts + TTS (per chapter)

```bash
python -m api.production.orchestrator --project david_and_goliath --chapter 1
python -m api.production.orchestrator --project david_and_goliath --chapter 2
# ... repeat for all content chapters
```

Each chapter gets: `script.json`, `scene_prompts.txt`, `character_sheets/`, `assets/audio_NNN.mp3`, `assets/audio_NNN.vtt`

### 3. Validate Assets

```bash
python -m api.production.orchestrator --project david_and_goliath --validate
```

Checks file integrity, duration limits, audio/VTT pairing, and story continuity.

### 4. Character Management (Cross-Chapter)

```bash
python -m api.production.character_manager --project david_and_goliath
```

Analyzes character timelines across all chapters, generates era-aware visual anchors via Gemini, creates optimized reference sheets, and injects visual descriptions into scene prompts.

### 5. Produce Scene Videos (Manual — Veo)

Use `scene_prompts.txt` + `character_sheets/` as reference in Veo to generate 8-second scene clips. Place in `scenes/scene_001.mp4`, etc. File naming is flexible — the pipeline auto-normalizes various formats.

### 6. Set Audio Priority (Optional)

```bash
# Specific scenes use Veo original audio (e.g., dialogue scenes)
python -m api.production.orchestrator \
  --project david_and_goliath --chapter 4 --set-audio 3,5,7 veo

# All scenes use mix mode
python -m api.production.orchestrator \
  --project david_and_goliath --chapter 4 --set-audio all mix
```

| Mode | Description |
|------|-------------|
| `tts` (default) | TTS narration + VTT subtitle burn-in |
| `veo` | Veo original audio + VTT subtitles only |
| `mix` | Veo audio (80%) + TTS (20%) blended |

### 7. Assemble Intro (ch00)

```bash
# Generate intro script + TTS
python -m api.production.orchestrator --project david_and_goliath --chapter 0

# Auto-assemble from existing chapter scenes (no new Veo work needed)
python -m api.production.orchestrator --project david_and_goliath --assemble-intro
```

### 8. Render + Merge

```bash
# Render individual chapter
python -m api.production.orchestrator \
  --project david_and_goliath --chapter 1 --resume-chapter

# Merge all chapters into master video
python -m api.production.orchestrator \
  --project david_and_goliath --merge-project
```

### 9. YouTube Shorts (9:16)

```bash
# Chapter full shorts — place 9:16 videos in scenes_shorts/, then:
python -m api.production.orchestrator \
  --project david_and_goliath --chapter 1 --resume-chapter --shorts

# Ch00 curation shorts (50-60s highlight reel)
python -m api.production.orchestrator \
  --project david_and_goliath --render-curation-shorts
```

### 10. AI Scene Quality Check

```bash
python -m api.production.orchestrator \
  --project david_and_goliath --validate-quality
```

Gemini 3 Flash analyzes scene keyframes for visual issues (artifact detection, character consistency, composition).

### 11. Thumbnails (A/B Test)

```bash
python -m api.production.orchestrator \
  --project david_and_goliath --generate-thumbnails
```

Generates 3 A/B test variants per video type (full movie, intro, shorts):
1. **Gemini** → 3 concepts (title + Imagen prompt + marketing angle)
2. **Imagen 3** → 16:9 cinematic background
3. **Nano Banana Pro** → 3D metallic gold title text compositing

### 12. YouTube Metadata

```bash
python -m api.production.orchestrator \
  --project david_and_goliath --generate-metadata
```

Generates SEO-optimized titles (×3), descriptions with chapter timestamps, hashtags, and tags for full movie, intro, and shorts.

## Project Structure

```
animation-generator/
├── api/
│   ├── production/
│   │   ├── orchestrator.py        # Main pipeline (Script→TTS→Render→Merge→CTA→Thumbnails)
│   │   ├── project_manager.py     # Project lifecycle & chapter management
│   │   ├── script_generator.py    # AI script generation with style presets
│   │   ├── character_db.py        # Character database & consistency engine
│   │   ├── character_manager.py   # Cross-chapter character sheet management
│   │   └── validators.py          # Audio/video/VTT asset validation
│   ├── services/
│   │   ├── ai.py                  # Vertex AI client (Gemini + Imagen + Nano Banana Pro)
│   │   ├── tts_service.py         # Edge-TTS + Gemini VTT subtitle generation
│   │   └── prompts.py             # Prompt templates for Bible storytelling
│   └── utils/
│       └── paths.py               # Centralized path management (Project/Chapter/Run)
├── config/
│   └── settings.py                # Style presets, video/TTS/Bible config
├── docs/
│   ├── production_pipeline.md     # Detailed production workflow (한국어)
│   ├── demo_prompt.txt            # Demo prompt reference
│   └── reference_david_and_goliath.txt  # Story reference material
├── scripts/
│   └── gen_battle_scenes.py       # Battle scene generation utility
├── run_bible.sh                   # Shell entry point (legacy single-run mode)
├── run_david_demo.py              # Demo script for david_and_goliath project
├── requirements.txt
└── .env.example
```

### Data Directory Structure (gitignored)

```
data/projects/{project_slug}/
├── project.json                    # Chapter plan & status tracking
├── character_db.json               # Character appearance database
├── character_timeline.json         # Cross-chapter character timeline (Phase 4)
├── character_visual_anchors.json   # Fixed appearance descriptions (Phase 4)
│
├── ch00_introduction/              # Auto-assembled from other chapters
│   ├── script.json                 # Intro script
│   ├── scene_prompts.txt           # 16:9 Veo prompts
│   ├── scene_prompts_shorts.txt    # 9:16 curation shorts prompts
│   ├── shorts_script.json          # Curation shorts structure
│   ├── intro_manual_map.json       # PD-curated scene-to-chapter mapping
│   ├── intro_assembly_map.json     # Auto-generated assembly map
│   ├── metadata.json               # Intro YouTube metadata
│   ├── shorts_metadata.json        # Shorts YouTube metadata
│   ├── assets/                     # TTS audio + VTT subtitles
│   ├── assets_shorts/              # Shorts-specific TTS (with asset_mapping.json)
│   ├── character_sheets/           # Character reference images
│   ├── scenes/                     # 16:9 scene videos
│   ├── scenes_shorts/              # 9:16 scene videos
│   ├── thumbnails/                 # A/B test thumbnails (concepts.json + variant_*.png)
│   └── chapter.mp4                 # Final intro video
│
├── ch01_the_shepherd_king_chosen/
│   ├── script.json                 # AI-generated scene script
│   ├── scene_prompts.txt           # Veo video prompts
│   ├── scene_prompts2.txt          # Veo bulk prompts (one-liner)
│   ├── assets/                     # audio_001.mp3, audio_001.vtt, ...
│   ├── character_sheets/           # Reference images for consistency
│   ├── scenes/                     # 16:9 scene videos (Veo output)
│   ├── scenes_shorts/              # 9:16 scene videos
│   ├── clips/ / clips_shorts/      # Rendered clips
│   ├── chapter.mp4                 # 16:9 master
│   └── chapter_shorts.mp4          # 9:16 shorts
│
├── ...
├── youtube_metadata.json           # Combined YouTube metadata
└── final/
    ├── master_{slug}.mp4           # Full merged video
    ├── metadata.json               # YouTube metadata (full movie)
    └── thumbnails/                 # A/B test thumbnails
        ├── concepts.json           # 3 concepts with prompts & angles
        ├── variant_a.png           # EPIC/ACTION variant
        ├── variant_b.png           # EMOTIONAL/CHARACTER variant
        └── variant_c.png           # CURIOSITY/MYSTERY variant
```

## Pipeline Phases

| # | Phase | Command | Description |
|---|-------|---------|-------------|
| 1 | Project Init | `project_manager create --title X --scripture Y` | AI-planned chapters |
| 2 | Script + TTS | `orchestrator --project X --chapter N` | Script, character sheets, TTS |
| 3 | QC Validation | `orchestrator --project X --validate` | Asset integrity check |
| 4 | Character Mgmt | `character_manager --project X` | Cross-chapter era-aware sheets |
| 5 | Veo Videos | *(manual)* | Scene video production |
| 6 | Intro Assembly | `orchestrator --project X --assemble-intro` | Semantic scene matching |
| 7 | Audio Priority | `orchestrator --project X --chapter N --set-audio SCENES MODE` | TTS/Veo/mix |
| 8 | Render & Merge | `orchestrator --project X --chapter N --resume-chapter` | FFmpeg render |
| 9 | Shorts | `orchestrator --project X --chapter N --resume-chapter --shorts` | 9:16 format |
| 10 | Curation Shorts | `orchestrator --project X --render-curation-shorts` | Ch00 highlight reel |
| 11 | Scene QC | `orchestrator --project X --validate-quality` | AI visual analysis |
| 12 | Thumbnails | `orchestrator --project X --generate-thumbnails` | Imagen + Nano Banana Pro |
| 13 | Metadata | `orchestrator --project X --generate-metadata` | YouTube-ready SEO |

## Style Presets

| Preset | Description |
|--------|-------------|
| `pixar_disney` | Pixar-quality 3D animation, Disney animated film style |
| `ark_films` | Cinematic Bible animation, Prince of Egypt quality |
| `watercolor` | Soft watercolor painting with visible brush strokes |
| `stained_glass` | Medieval stained glass window art, jewel-tone colors |

## Character Consistency System

The pipeline uses multiple techniques to maintain character visual consistency across scenes:

1. **Rare-Name Anchoring** — Unique identifiers (e.g., "Davith Shepherdael") fix characters in the AI's latent space
2. **Stream Descriptions** — Uninterrupted character description strings embedded in every scene prompt
3. **Negative Guidance** — Per-character negative prompts to prevent visual drift
4. **Era-Aware Sheets** — Character reference images generated for each life stage (e.g., David as shepherd boy vs. king)
5. **Visual Anchor Injection** — Automated inline description insertion into scene prompts (via `character_manager`)

## Multi-Language Support

| Language | Voice | Code |
|----------|-------|------|
| English | `en-US-AndrewNeural` | `en` |
| Korean | `ko-KR-SunHiNeural` | `ko` |
| Japanese | `ja-JP-NanamiNeural` | `ja` |
| Chinese | `zh-CN-XiaoxiaoNeural` | `zh` |
| Spanish | `es-ES-AlvaroNeural` | `es` |

## Utility Commands

| Command | Description |
|---------|-------------|
| `orchestrator --project X --project-status` | Show project status |
| `orchestrator --char-sheet CHARACTER_ID` | Print character sheet prompt |
| `orchestrator --char-json CHARACTER_ID` | Print character JSON metadata |
| `orchestrator --regen-prompts RUN_ID` | Regenerate prompts for legacy run |
| `character_manager --project X --timeline-only` | Timeline analysis only |
| `character_manager --project X --inject-only` | Visual anchor injection only |

## Detailed Documentation

See [production_pipeline.md](docs/production_pipeline.md) for the complete production workflow with phase-by-phase details (한국어).

## License

Private project. All rights reserved.
