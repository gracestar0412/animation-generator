# 📖 Bible Animation Generator

AI-powered production pipeline for Bible story animations. Automates script generation, TTS narration, character consistency, and video assembly for long-form chapter-based projects.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Production Pipeline                         │
│                                                                 │
│  Project Init ─→ Script Gen ─→ TTS ─→ [Veo Video] ─→ Render   │
│   (AI Plan)       (Gemini)    (Edge)   (Human Loop)   (FFmpeg)  │
│                                                                 │
│  ─→ Merge ─→ CTA Overlay ─→ Metadata ─→ YouTube-Ready          │
│    (FFmpeg)    (Green Screen)   (Gemini)                        │
└─────────────────────────────────────────────────────────────────┘
```

### Key Features

- **AI Script Generation** — Gemini-powered scene-by-scene scripts with structured video prompts
- **Character Consistency** — Rare-name anchoring, stream descriptions, and era-aware reference sheets
- **Multi-format Output** — 16:9 long-form chapters + 9:16 YouTube Shorts
- **Intro Auto-Assembly** — Reuses existing chapter scenes for introduction montage
- **CTA Overlay** — Automated green-screen subscribe/like overlay
- **Configurable Art Styles** — Pixar/Disney, Ark Films, Watercolor, Stained Glass presets

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

This generates `project.json` with AI-planned chapter structure, `character_db.json`, and all chapter directories.

### 2. Generate Scripts + TTS (per chapter)

```bash
python -m api.production.orchestrator --project david_and_goliath --chapter 1
python -m api.production.orchestrator --project david_and_goliath --chapter 2
# ... repeat for all content chapters
```

Each chapter gets: `script.json`, `scene_prompts.txt`, `assets/audio_NNN.mp3`, `assets/audio_NNN.vtt`

### 3. Produce Scene Videos (Manual — Veo)

Use `scene_prompts.txt` + `character_sheets/` as reference in Veo to generate 8-second scene clips. Place them in `scenes/scene_001.mp4`, etc.

File naming is flexible — the pipeline auto-normalizes various formats.

### 4. Assemble Intro (ch00)

```bash
# Generate intro script + TTS
python -m api.production.orchestrator --project david_and_goliath --chapter 0

# Auto-assemble from existing chapter scenes (no new Veo work needed)
python -m api.production.orchestrator --project david_and_goliath --assemble-intro
```

### 5. Render + Merge

```bash
# Render individual chapter
python -m api.production.orchestrator \
  --project david_and_goliath --chapter 1 --resume-chapter

# Merge all chapters into master video
python -m api.production.orchestrator \
  --project david_and_goliath --merge-project
```

### 6. YouTube Shorts (9:16)

```bash
# Place 9:16 videos in scenes_shorts/, then:
python -m api.production.orchestrator \
  --project david_and_goliath --chapter 1 --resume-chapter --shorts
```

### 7. YouTube Metadata

```bash
python -m api.production.orchestrator \
  --project david_and_goliath --generate-metadata
```

## Project Structure

```
animation-generator/
├── api/
│   ├── production/
│   │   ├── orchestrator.py        # Main pipeline (Script→TTS→Render→Merge→CTA)
│   │   ├── project_manager.py     # Project lifecycle & chapter management
│   │   ├── script_generator.py    # AI script generation with style presets
│   │   ├── character_db.py        # Character database & consistency engine
│   │   ├── character_manager.py   # Cross-chapter character sheet management
│   │   └── validators.py          # Audio/video/VTT asset validation
│   ├── services/
│   │   ├── ai.py                  # Google Vertex AI client (Gemini + Imagen)
│   │   ├── tts_service.py         # Edge-TTS + VTT subtitle generation
│   │   └── prompts.py             # Prompt templates for Bible storytelling
│   └── utils/
│       └── paths.py               # Centralized path management
├── config/
│   └── settings.py                # Style presets, video/TTS/Bible config
├── docs/
│   └── production_pipeline.md     # Detailed production workflow docs
├── scripts/
│   └── gen_battle_scenes.py       # Battle scene generation utility
├── run_bible.sh                   # Shell entry point
├── requirements.txt
└── .env.example
```

### Data Directory Structure (gitignored)

```
data/projects/{project_slug}/
├── project.json                    # Chapter plan & status tracking
├── character_db.json               # Character appearance database
├── ch00_introduction/              # Auto-assembled from other chapters
│   ├── script.json
│   ├── intro_manual_map.json       # PD-curated scene-to-chapter mapping
│   ├── intro_assembly_map.json     # Auto-generated assembly map
│   ├── assets/                     # TTS audio + VTT subtitles
│   ├── scenes/                     # Copied from source chapters
│   ├── clips/                      # Rendered clips (video+audio+subs)
│   └── chapter.mp4                 # Final intro video
├── ch01_the_shepherd_king_chosen/
│   ├── script.json                 # AI-generated scene script
│   ├── scene_prompts.txt           # Veo video prompts
│   ├── assets/                     # audio_001.mp3, audio_001.vtt, ...
│   ├── character_sheets/           # Reference images for consistency
│   ├── scenes/                     # 16:9 scene videos (Veo output)
│   ├── scenes_shorts/              # 9:16 scene videos
│   ├── clips/ / clips_shorts/      # Rendered clips
│   ├── chapter.mp4                 # 16:9 master
│   └── chapter_shorts.mp4          # 9:16 shorts
├── ...
├── youtube_metadata.json           # Combined YouTube metadata
└── final/
    ├── master_{slug}.mp4           # Full merged video
    └── metadata.json               # YouTube metadata
```

## Pipeline Phases

| # | Phase | Command | Description |
|---|-------|---------|-------------|
| 1 | Project Init | `project_manager create --title X --scripture Y` | AI-planned chapters |
| 2 | Script + TTS | `orchestrator --project X --chapter N` | Script, character sheets, TTS |
| 3 | QC Validation | `orchestrator --project X --validate` | Asset integrity check |
| 4 | Character Mgmt | `character_manager --project X` | Cross-chapter consistency |
| 5 | Veo Videos | *(manual)* | Scene video production |
| 6 | Intro Assembly | `orchestrator --project X --assemble-intro` | Reuse existing scenes |
| 7 | Render & Merge | `orchestrator --project X --chapter N --resume-chapter` | FFmpeg render |
| 8 | Shorts | `orchestrator --project X --chapter N --resume-chapter --shorts` | 9:16 format |
| 9 | Metadata | `orchestrator --project X --generate-metadata` | YouTube-ready metadata |

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

## Detailed Documentation

See [production_pipeline.md](docs/production_pipeline.md) for the complete production workflow with phase-by-phase details.

## License

Private project. All rights reserved.
