"""
Centralized path management for Bible Animation Generator.
Structure:
  data/runs/{run_id}/
    ├── script.json
    ├── scene_prompts.txt
    ├── character_db.json
    ├── assets/   (TTS audio + VTT)
    ├── scenes/   (user-provided scene videos)
    ├── clips/    (rendered clips: video + audio + subtitles)
    └── final/    (merged master video)
"""

import os


class PathManager:
    def __init__(self, run_id: str, base_dir: str = "data"):
        self.run_id = run_id
        self.root = os.path.abspath(os.path.join(base_dir, "runs", run_id))

        self.assets = os.path.join(self.root, "assets")
        self.scenes = os.path.join(self.root, "scenes")
        self.clips = os.path.join(self.root, "clips")

    # --- Properties ---

    @property
    def final(self):
        return os.path.join(self.root, "final")

    @property
    def script_file(self):
        return os.path.join(self.root, "script.json")

    @property
    def scene_prompts_file(self):
        return os.path.join(self.root, "scene_prompts.txt")

    @property
    def character_db_file(self):
        return os.path.join(self.root, "character_db.json")

    @property
    def manifest_file(self):
        return os.path.join(self.root, "manifest.json")

    @property
    def rendered(self):
        return self.clips

    # --- Asset paths ---

    def get_audio_path(self, scene_id: int) -> str:
        return os.path.join(self.assets, f"audio_{scene_id:03d}.mp3")

    def get_vtt_path(self, scene_id: int) -> str:
        return os.path.join(self.assets, f"audio_{scene_id:03d}.vtt")

    def get_scene_video_path(self, scene_id: int) -> str:
        """User-provided scene video."""
        return os.path.join(self.scenes, f"scene_{scene_id:03d}.mp4")

    def get_clip_path(self, scene_id: int) -> str:
        """Rendered clip (scene video + audio + subtitles)."""
        return os.path.join(self.clips, f"clip_{scene_id:03d}.mp4")

    @property
    def final_video(self):
        return os.path.join(self.final, f"master_{self.run_id}.mp4")

    # --- Directory management ---

    def ensure_dirs(self):
        """Create the entire directory tree."""
        for d in [self.assets, self.scenes, self.clips, self.final]:
            os.makedirs(d, exist_ok=True)
        return self.root


class ProjectPathManager:
    """
    Path manager for chapter-based long-form projects.

    Structure:
      data/projects/{project_slug}/
        ├── project.json
        ├── character_db.json
        ├── character_sheets/
        ├── ch00_introduction/
        │   ├── script.json
        │   ├── scene_prompts.txt / scene_prompts2.txt
        │   ├── assets/
        │   ├── scenes/
        │   ├── clips/
        │   └── chapter.mp4
        ├── ch01_.../
        ├── ...
        └── final/
            ├── master_{slug}.mp4
            └── metadata.json
    """

    def __init__(self, project_slug: str, base_dir: str = "data"):
        self.slug = project_slug
        self.root = os.path.abspath(os.path.join(base_dir, "projects", project_slug))

    # --- Project-level paths ---

    @property
    def project_json(self):
        return os.path.join(self.root, "project.json")

    @property
    def character_db_file(self):
        return os.path.join(self.root, "character_db.json")

    @property
    def character_sheets_dir(self):
        return os.path.join(self.root, "character_sheets")

    @property
    def final_dir(self):
        return os.path.join(self.root, "final")

    @property
    def final_video(self):
        return os.path.join(self.final_dir, f"master_{self.slug}.mp4")

    @property
    def metadata_file(self):
        return os.path.join(self.final_dir, "metadata.json")

    # --- Chapter paths ---

    def chapter_dir(self, chapter_idx: int, chapter_slug: str) -> str:
        """Get the directory for a specific chapter."""
        return os.path.join(self.root, f"ch{chapter_idx:02d}_{chapter_slug}")

    def chapter_path_manager(self, chapter_idx: int, chapter_slug: str) -> 'ChapterPathManager':
        """Get a ChapterPathManager for a specific chapter."""
        return ChapterPathManager(self, chapter_idx, chapter_slug)

    # --- Directory management ---

    def ensure_dirs(self):
        """Create base project directories."""
        os.makedirs(self.root, exist_ok=True)
        os.makedirs(self.character_sheets_dir, exist_ok=True)
        os.makedirs(self.final_dir, exist_ok=True)
        return self.root


class ChapterPathManager:
    """
    Path manager for a single chapter within a project.
    Provides the same interface as PathManager for compatibility.
    """

    def __init__(self, project_pm: ProjectPathManager, chapter_idx: int, chapter_slug: str):
        self.project_pm = project_pm
        self.chapter_idx = chapter_idx
        self.chapter_slug = chapter_slug
        self.root = project_pm.chapter_dir(chapter_idx, chapter_slug)

        self.assets = os.path.join(self.root, "assets")
        self.scenes = os.path.join(self.root, "scenes")
        self.clips = os.path.join(self.root, "clips")

        # Shorts (9:16) directories
        self.scenes_shorts = os.path.join(self.root, "scenes_shorts")
        self.clips_shorts = os.path.join(self.root, "clips_shorts")

    @property
    def script_file(self):
        return os.path.join(self.root, "script.json")

    @property
    def scene_prompts_file(self):
        return os.path.join(self.root, "scene_prompts.txt")

    @property
    def chapter_video(self):
        return os.path.join(self.root, "chapter.mp4")

    @property
    def chapter_shorts_video(self):
        return os.path.join(self.root, "chapter_shorts.mp4")

    @property
    def rendered(self):
        return self.clips

    @property
    def final(self):
        return self.root  # chapter.mp4 lives at chapter root

    @property
    def final_video(self):
        return self.chapter_video

    def get_audio_path(self, scene_id: int) -> str:
        return os.path.join(self.assets, f"audio_{scene_id:03d}.mp3")

    def get_vtt_path(self, scene_id: int) -> str:
        return os.path.join(self.assets, f"audio_{scene_id:03d}.vtt")

    def get_scene_video_path(self, scene_id: int, shorts: bool = False) -> str:
        base = self.scenes_shorts if shorts else self.scenes
        return os.path.join(base, f"scene_{scene_id:03d}.mp4")

    def get_clip_path(self, scene_id: int, shorts: bool = False) -> str:
        base = self.clips_shorts if shorts else self.clips
        return os.path.join(base, f"clip_{scene_id:03d}.mp4")

    def ensure_dirs(self):
        """Create chapter directory tree."""
        for d in [self.assets, self.scenes, self.clips,
                  self.scenes_shorts, self.clips_shorts]:
            os.makedirs(d, exist_ok=True)
        return self.root

