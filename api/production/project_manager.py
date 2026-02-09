"""
Project Manager for long-form chapter-based Bible animation production.

Manages project.json, chapter lifecycle, and final merge.
"""

import json
import logging
import os
import re
import subprocess
import time
from typing import Optional

from api.utils.paths import ProjectPathManager, ChapterPathManager

logger = logging.getLogger("ProjectManager")

# Chapter statuses
STATUS_PENDING = "pending"
STATUS_SCRIPTED = "scripted"
STATUS_TTS_DONE = "tts_done"
STATUS_SCENES_READY = "scenes_ready"
STATUS_RENDERED = "rendered"
STATUS_MERGED = "merged"


def slugify(text: str) -> str:
    """Convert title to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s-]+", "_", text)
    return text


class ProjectManager:
    """
    Manages a long-form chapter-based Bible animation project.

    Lifecycle per chapter:
        pending → scripted → tts_done → scenes_ready → rendered → merged
    """

    def __init__(self, project_slug: str, base_dir: str = "data"):
        self.pm = ProjectPathManager(project_slug, base_dir)
        self.project_data = None
        self._load()

    def _load(self):
        """Load project.json if it exists."""
        if os.path.exists(self.pm.project_json):
            with open(self.pm.project_json, "r", encoding="utf-8") as f:
                self.project_data = json.load(f)
        else:
            self.project_data = None

    def _save(self):
        """Save project.json to disk."""
        with open(self.pm.project_json, "w", encoding="utf-8") as f:
            json.dump(self.project_data, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------ #
    #  Project Creation
    # ------------------------------------------------------------------ #

    def create_project(
        self,
        title: str,
        scripture_ref: str,
        language: str = "en",
        style_preset: str = "pixar_disney",
    ) -> dict:
        """Create a new project with metadata (no chapters yet)."""
        self.pm.ensure_dirs()

        self.project_data = {
            "title": title,
            "slug": self.pm.slug,
            "scripture_ref": scripture_ref,
            "language": language,
            "style_preset": style_preset,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "chapters": [],
            "status": "created",
        }
        self._save()
        logger.info(f"📁 Project created: {self.pm.root}")
        return self.project_data

    # ------------------------------------------------------------------ #
    #  Chapter Planning
    # ------------------------------------------------------------------ #

    def set_chapters(self, chapters: list[dict]):
        """
        Set the chapter plan for this project.

        Each chapter dict:
          {
            "title": "The Forgotten Son",
            "slug": "the_forgotten_son",
            "duration_target": "2m20s",
            "key_events": "Samuel anoints David",
            "scripture_range": "1 Samuel 16:1-13"
          }

        ch00 (introduction) and chNN (outro) are expected to be included.
        """
        self.project_data["chapters"] = []
        for idx, ch in enumerate(chapters):
            slug = ch.get("slug", slugify(ch["title"]))
            chapter_entry = {
                "index": idx,
                "title": ch["title"],
                "slug": slug,
                "duration_target": ch.get("duration_target", "2m"),
                "key_events": ch.get("key_events", ""),
                "scripture_range": ch.get("scripture_range", ""),
                "status": STATUS_PENDING,
                "dir": f"ch{idx:02d}_{slug}",
            }
            self.project_data["chapters"].append(chapter_entry)

            # Create chapter directory
            cpm = self.pm.chapter_path_manager(idx, slug)
            cpm.ensure_dirs()

        self.project_data["status"] = "planned"
        self._save()
        logger.info(f"📋 {len(chapters)} chapters planned")
        return self.project_data["chapters"]

    # ------------------------------------------------------------------ #
    #  Chapter Status
    # ------------------------------------------------------------------ #

    def get_chapter(self, chapter_idx: int) -> Optional[dict]:
        """Get chapter data by index."""
        for ch in self.project_data.get("chapters", []):
            if ch["index"] == chapter_idx:
                return ch
        return None

    def update_chapter_status(self, chapter_idx: int, status: str):
        """Update a chapter's status."""
        ch = self.get_chapter(chapter_idx)
        if ch:
            ch["status"] = status
            self._save()
            logger.info(f"📌 Chapter {chapter_idx} ({ch['title']}): {status}")

    def get_chapter_pm(self, chapter_idx: int) -> Optional[ChapterPathManager]:
        """Get ChapterPathManager for a chapter."""
        ch = self.get_chapter(chapter_idx)
        if not ch:
            return None
        return self.pm.chapter_path_manager(ch["index"], ch["slug"])

    def get_next_pending(self) -> Optional[dict]:
        """
        Get the next chapter that hasn't been started.
        Production order: ch01..chN → outro → intro (ch00 is LAST).
        Intro is produced last because it uses highlight scenes from completed chapters.
        """
        chapters = self.project_data.get("chapters", [])
        intro = None

        # First pass: find pending non-intro chapters
        for ch in chapters:
            if ch["status"] != STATUS_PENDING:
                continue
            if ch["slug"] == "introduction":
                intro = ch
                continue
            return ch

        # All non-intro chapters done → now do intro
        if intro:
            return intro

        return None

    def get_all_chapters(self) -> list[dict]:
        """Get all chapters."""
        return self.project_data.get("chapters", [])

    def get_rendered_chapters(self) -> list[dict]:
        """Get chapters that have been rendered (have chapter.mp4)."""
        rendered = []
        for ch in self.project_data.get("chapters", []):
            if ch["status"] in (STATUS_RENDERED, STATUS_MERGED):
                rendered.append(ch)
        return rendered

    # ------------------------------------------------------------------ #
    #  Project-Level Merge
    # ------------------------------------------------------------------ #

    def merge_all_chapters(self) -> Optional[str]:
        """
        Merge all rendered chapter videos into the final master video.
        Returns the path to the master video, or None on failure.
        """
        chapters = self.get_all_chapters()
        chapter_videos = []

        for ch in chapters:
            cpm = self.pm.chapter_path_manager(ch["index"], ch["slug"])
            video_path = cpm.chapter_video
            if os.path.exists(video_path) and os.path.getsize(video_path) > 1024:
                chapter_videos.append(video_path)
            else:
                logger.warning(
                    f"⚠️ Chapter {ch['index']} ({ch['title']}): "
                    f"video not found, skipping"
                )

        if not chapter_videos:
            logger.error("❌ No chapter videos found to merge")
            return None

        logger.info(f"🎬 Merging {len(chapter_videos)} chapters → master video")

        # Create concat list file
        concat_file = os.path.join(self.pm.root, "concat_chapters.txt")
        with open(concat_file, "w") as f:
            for vp in chapter_videos:
                f.write(f"file '{vp}'\n")

        output_path = self.pm.final_video
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"❌ Merge failed: {result.stderr[-500:]}")
            return None

        # Clean up concat file
        os.remove(concat_file)

        # Calculate total duration
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", output_path],
                capture_output=True, text=True,
            )
            duration = float(probe.stdout.strip())
            logger.info(
                f"✅ Master video: {output_path} "
                f"({duration:.1f}s / {duration/60:.1f}min)"
            )
        except Exception:
            logger.info(f"✅ Master video: {output_path}")

        # Update all merged chapters
        for ch in chapters:
            if ch["status"] == STATUS_RENDERED:
                ch["status"] = STATUS_MERGED
        self.project_data["status"] = "complete"
        self._save()

        return output_path

    # ------------------------------------------------------------------ #
    #  Chapter Timestamps (for YouTube description)
    # ------------------------------------------------------------------ #

    def generate_chapter_timestamps(self) -> list[dict]:
        """
        Calculate YouTube-style chapter timestamps from chapter video durations.
        Returns: [{"title": "Introduction", "timestamp": "00:00"}, ...]
        """
        timestamps = []
        cumulative_seconds = 0.0

        for ch in self.get_all_chapters():
            # Format timestamp
            mins = int(cumulative_seconds // 60)
            secs = int(cumulative_seconds % 60)
            ts = f"{mins:02d}:{secs:02d}"

            label = ch["title"]
            if ch["index"] > 0 and not label.lower().startswith("chapter"):
                if "intro" not in label.lower() and "outro" not in label.lower():
                    label = f"Chapter {ch['index']}: {label}"

            timestamps.append({
                "index": ch["index"],
                "title": label,
                "timestamp": ts,
            })

            # Get video duration for this chapter
            cpm = self.pm.chapter_path_manager(ch["index"], ch["slug"])
            video_path = cpm.chapter_video
            if os.path.exists(video_path):
                try:
                    probe = subprocess.run(
                        ["ffprobe", "-v", "quiet",
                         "-show_entries", "format=duration",
                         "-of", "csv=p=0", video_path],
                        capture_output=True, text=True,
                    )
                    cumulative_seconds += float(probe.stdout.strip())
                except Exception:
                    pass

        return timestamps

    # ------------------------------------------------------------------ #
    #  Info / Display
    # ------------------------------------------------------------------ #

    def print_status(self):
        """Print project status overview."""
        if not self.project_data:
            logger.info("❌ No project loaded")
            return

        logger.info(f"\n📖 Project: {self.project_data['title']}")
        logger.info(f"   Scripture: {self.project_data['scripture_ref']}")
        logger.info(f"   Style: {self.project_data['style_preset']}")
        logger.info(f"   Status: {self.project_data['status']}")
        logger.info(f"   Chapters: {len(self.project_data.get('chapters', []))}")
        logger.info("")

        for ch in self.project_data.get("chapters", []):
            status_emoji = {
                STATUS_PENDING: "⬜",
                STATUS_SCRIPTED: "📝",
                STATUS_TTS_DONE: "🔊",
                STATUS_SCENES_READY: "🎥",
                STATUS_RENDERED: "✅",
                STATUS_MERGED: "🏁",
            }.get(ch["status"], "❓")

            logger.info(
                f"   {status_emoji} ch{ch['index']:02d} "
                f"{ch['title']:40s} [{ch['status']}]"
            )
