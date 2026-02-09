"""
Asset validators for Bible Animation Generator.
Checks audio, video, and subtitle file integrity.
"""

import os
import subprocess
import logging

logger = logging.getLogger("validators")


def validate_audio_asset(path: str) -> bool:
    """Check if audio file exists, is non-trivial, and has valid duration."""
    if not os.path.exists(path):
        return False
    if os.path.getsize(path) < 1024:  # Less than 1KB
        logger.warning(f"Audio too small: {path}")
        return False

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10
        )
        duration = float(result.stdout.strip())
        if duration < 0.5:
            logger.warning(f"Audio too short ({duration}s): {path}")
            return False
        return True
    except Exception as e:
        logger.warning(f"Audio validation failed for {path}: {e}")
        return False


def validate_video_asset(path: str) -> bool:
    """Check if video file exists and is valid."""
    if not os.path.exists(path):
        return False
    if os.path.getsize(path) < 10 * 1024:  # Less than 10KB
        logger.warning(f"Video too small: {path}")
        return False

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10
        )
        duration = float(result.stdout.strip())
        if duration < 1.0:
            logger.warning(f"Video too short ({duration}s): {path}")
            return False
        return True
    except Exception as e:
        logger.warning(f"Video validation failed for {path}: {e}")
        return False


def validate_vtt_asset(path: str) -> bool:
    """Check if VTT file exists and has content."""
    if not os.path.exists(path):
        return False
    if os.path.getsize(path) < 10:
        logger.warning(f"VTT too small: {path}")
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return "WEBVTT" in content
    except Exception:
        return False


def validate_scene_videos(scenes_dir: str, scene_count: int) -> dict:
    """
    Check which scene videos are present in the scenes/ directory.
    Returns: {"present": [1,2,3], "missing": [4,5]}
    """
    present = []
    missing = []

    for i in range(1, scene_count + 1):
        path = os.path.join(scenes_dir, f"scene_{i:03d}.mp4")
        if validate_video_asset(path):
            present.append(i)
        else:
            missing.append(i)

    return {"present": present, "missing": missing}


def get_duration(path: str) -> float:
    """Get media file duration in seconds."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0
