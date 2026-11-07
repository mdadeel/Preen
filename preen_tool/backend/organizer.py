"""Backend logic for the Folder Organizer feature.

This module groups files in a selected directory by extension or type
and moves them into categorized subfolders (e.g., Documents, Images,
Archives). It respects Simulate mode and prevents overwriting existing
files by appending a suffix.
"""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

# Common extension groups
EXT_GROUPS: Dict[str, str] = {
    # Documents
    ".pdf": "Documents",
    ".doc": "Documents",
    ".docx": "Documents",
    ".txt": "Documents",
    ".odt": "Documents",
    ".rtf": "Documents",
    ".xls": "Documents",
    ".xlsx": "Documents",
    ".csv": "Documents",
    ".ppt": "Documents",
    ".pptx": "Documents",
    ".md": "Documents",
    # Images
    ".jpg": "Images",
    ".jpeg": "Images",
    ".png": "Images",
    ".gif": "Images",
    ".svg": "Images",
    ".bmp": "Images",
    ".tiff": "Images",
    ".webp": "Images",
    # Archives
    ".zip": "Archives",
    ".tar": "Archives",
    ".gz": "Archives",
    ".bz2": "Archives",
    ".xz": "Archives",
    ".7z": "Archives",
    ".rar": "Archives",
    ".iso": "Archives",
    # Audio
    ".mp3": "Audio",
    ".wav": "Audio",
    ".ogg": "Audio",
    ".flac": "Audio",
    ".m4a": "Audio",
    # Video
    ".mp4": "Video",
    ".mkv": "Video",
    ".avi": "Video",
    ".mov": "Video",
    ".webm": "Video",
    # Code/Scripts
    ".py": "Code",
    ".js": "Code",
    ".html": "Code",
    ".css": "Code",
    ".sh": "Code",
    ".c": "Code",
    ".cpp": "Code",
    ".java": "Code",
    ".go": "Code",
    ".rs": "Code",
    ".json": "Code",
    ".xml": "Code",
    # Executables
    ".exe": "Executables",
    ".bin": "Executables",
    ".sh": "Executables",
    ".run": "Executables",
    # Others
    ".deb": "Packages",
    ".rpm": "Packages",
    ".flatpakref": "Packages",
    ".appimage": "Packages",
}

def get_category(filepath: Path) -> str:
    """Return the category for a file based on its extension."""
    ext = filepath.suffix.lower()
    return EXT_GROUPS.get(ext, "Others")

def generate_safe_path(dest_dir: Path, filename: str) -> Path:
    """Generate a safe destination path, appending a suffix if the file exists."""
    dest_path = dest_dir / filename
    counter = 1
    while dest_path.exists():
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        new_filename = f"{stem}_{counter}{suffix}"
        dest_path = dest_dir / new_filename
        counter += 1
    return dest_path

def organize_folder(
    folder_path: str,
    simulate: bool = False,
    log_callback=None
) -> Tuple[bool, List[str]]:
    """
    Organize files in the selected folder into categorized subfolders.

    :param folder_path: The root directory to organize.
    :param simulate: If True, only log actions without moving files.
    :param log_callback: Function to log messages (optional).
    :return: (success, list_of_logs)
    """
    root = Path(folder_path)
    if not root.exists() or not root.is_dir():
        msg = f"Error: Directory does not exist: {folder_path}"
        if log_callback:
            log_callback(msg)
        return False, [msg]

    logs = []
    success = True

    # Gather files (ignore directories and hidden files for safety)
    files = [f for f in root.iterdir() if f.is_file() and not f.name.startswith(".")]

    if not files:
        msg = "No files found to organize."
        if log_callback:
            log_callback(msg)
        logs.append(msg)
        return True, logs

    for file_path in files:
        category = get_category(file_path)
        dest_dir = root / category
        
        # Create category directory if it doesn't exist (unless simulating)
        if not simulate and not dest_dir.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)
            log_msg = f"Created folder: {category}"
            if log_callback:
                log_callback(log_msg)
            logs.append(log_msg)

        dest_path = generate_safe_path(dest_dir, file_path.name)

        action_msg = f"Moving '{file_path.name}' -> '{category}/{dest_path.name}'"
        if log_callback:
            log_callback(action_msg)
        logs.append(action_msg)

        if not simulate:
            try:
                shutil.move(str(file_path), str(dest_path))
            except Exception as e:
                err_msg = f"Failed to move '{file_path.name}': {e}"
                if log_callback:
                    log_callback(err_msg)
                logs.append(err_msg)
                success = False

    if simulate:
        msg = "Simulation complete. No files were moved."
        if log_callback:
            log_callback(msg)
        logs.append(msg)

    return success, logs
