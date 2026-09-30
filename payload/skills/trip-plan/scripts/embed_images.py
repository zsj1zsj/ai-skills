"""Embed only authorized run-local raster images; no fetches or dependencies."""
import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import sys

from image_assets import data_uri, manifest_images


class ImageTag(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.attrs = attrs


def embed(html_path, manifest_path):
    html_path = Path(html_path)
    if html_path.is_symlink() or html_path.name != "trip.html":
        raise ValueError("Output must be run-local trip.html, not a symlink")
    _, allowed = manifest_images(html_path, manifest_path)
    text = html_path.read_text(encoding="utf-8-sig")
    used, cache = [], {}

    def replace(match):
        tag = match.group(0)
        parser = ImageTag()
        parser.feed(tag)
        attrs = getattr(parser, "attrs", [])
        srcs = [value for name, value in attrs if name == "src"]
        if len(srcs) != 1 or srcs[0] not in allowed:
            raise ValueError("Every img must use exactly one manifest-authorized local src")
        if any(name in ("srcset", "onerror", "onload") for name, _ in attrs):
            raise ValueError("Image srcset/events are forbidden")
        src = srcs[0]
        if src not in cache:
            cache[src] = data_uri(allowed[src][0])
        # Require quoted src so substitution is unambiguous. Preserve other markup.
        pattern = r'''(\s+src\s*=\s*)(["'])(.*?)\2'''
        updated, count = re.subn(pattern, lambda m: m[1] + m[2] + cache[src] + m[2], tag, flags=re.I | re.S)
        if count != 1:
            raise ValueError("Image src must be quoted exactly once")
        used.append(src)
        return updated

    result = re.sub(r"<img\b[^>]*>", replace, text, flags=re.I)
    if not used:
        return {"embedded": 0, "bytes": html_path.stat().st_size, "note": "No images; file unchanged"}
    # Nothing is written until all references and image bytes pass validation.
    html_path.write_text(result, encoding="utf-8")
    return {"embedded": len(used), "bytes": html_path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(embed(args.html, args.manifest))
        return 0
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
