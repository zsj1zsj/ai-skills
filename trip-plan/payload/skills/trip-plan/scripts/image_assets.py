"""Small shared boundary for manifest-authorized run-local raster images. No network."""
import base64
import json
from pathlib import Path, PurePosixPath

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024


def safe_path(path):
    """Reject symlinks/junctions at every existing component, including ancestors.

    Run directories are parent-owned; this is not a sandbox against a concurrent
    hostile local writer replacing directories between checks and IO.
    """
    path = Path(path).absolute()
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("UNC/network/device paths are forbidden")
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Symlinks/junctions are forbidden")
    if path.resolve() != path:
        raise ValueError("Path alias/escape is forbidden")
    return path


def raster_type(content):
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", ".gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise ValueError("Image signature is not an allowed raster")


def manifest_images(html_path, manifest_path):
    root = safe_path(Path(html_path).absolute().parent)
    manifest_path = safe_path(manifest_path)
    expected = root / "images" / "manifest.json"
    if (root / "images").is_symlink() or expected.is_symlink() or manifest_path.resolve() != expected:
        raise ValueError("Manifest must be the run-local images/manifest.json, without symlinks")
    data = json.loads(expected.read_text(encoding="utf-8-sig"))
    entries = data.get("images")
    if not isinstance(entries, list) or data.get("mode") not in ("no_photos", "local_photos"):
        raise ValueError("Invalid images manifest mode/images")
    if data["mode"] == "no_photos" and entries:
        raise ValueError("no_photos manifest must have images: []")
    allowed = {}
    total = 0
    for entry in entries:
        if entry.get("status") != "ok":
            continue
        src = entry.get("src", "")
        if not isinstance(src, str) or any(c in src for c in "\\:%?#\x00"):
            raise ValueError("Invalid image src")
        parts = PurePosixPath(src).parts
        if len(parts) < 2 or parts[0] != "images" or any(p in (".", "..") for p in src.split("/")):
            raise ValueError("Only exact images/ paths without traversal are allowed")
        path = safe_path(root.joinpath(*parts))
        if src in allowed or not path.resolve().is_relative_to(root / "images"):
            raise ValueError("Duplicate src or image path escape")
        cursor = root
        for part in parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Image symlinks are forbidden")
        if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            raise ValueError("Image must be an existing PNG/JPEG/GIF/WebP")
        size = path.stat().st_size
        if not 0 < size <= MAX_IMAGE_BYTES:
            raise ValueError("Image empty or exceeds 5 MiB")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Manifest images exceed 20 MiB")
        if not entry.get("stop_id") or not entry.get("licence") or not str(entry.get("page", "")).startswith(("https://", "http://")):
            raise ValueError("Image missing stop_id/licence/source page")
        allowed[src] = (path, entry)
    return data, allowed


def data_uri(path):
    # Bounded read even if the file changed since stat; no arbitrary file types.
    with path.open("rb") as stream:
        content = stream.read(MAX_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Image empty or exceeds 5 MiB")
    if content.startswith(b"\x89PNG\r\n\x1a\n") and path.suffix.lower() == ".png":
        mime = "image/png"
    elif content.startswith(b"\xff\xd8\xff") and path.suffix.lower() in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif content[:6] in (b"GIF87a", b"GIF89a") and path.suffix.lower() == ".gif":
        mime = "image/gif"
    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP" and path.suffix.lower() == ".webp":
        mime = "image/webp"
    else:
        raise ValueError("Image signature does not match allowed raster extension")
    return f"data:{mime};base64," + base64.b64encode(content).decode("ascii")
