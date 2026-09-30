"""Check actual trip.html structure, coverage and offline assets (not browser/feasibility)."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

from image_assets import data_uri, manifest_images

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
FORBIDDEN = {"script", "link", "base", "iframe", "object", "embed", "audio", "video", "source", "track", "form", "button", "foreignobject", "animate", "animatemotion", "animatetransform", "set"}


class Report(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors, self.stack, self.nodes = [], [], []
        self.ids, self.days, self.stops, self.images = {}, [], [], []
        self.dining, self.dining_text = [], {}
        self.css, self.text, self.credits, self.decisions, self.summary = [], [], [], [], []
        self.lang = self.viewport = self.top_closed = False
        self.pre_day_nodes = []

    def handle_starttag(self, tag, attrs):
        pairs = attrs
        attrs = dict(attrs)
        if len(attrs) != len(pairs):
            self.errors.append(f"Duplicate attribute on {tag}")
        if tag in FORBIDDEN:
            self.errors.append(f"Nonstatic/asset element forbidden: {tag}")
        if tag == "input":
            allowed = {"type", "id", "class", "style", "checked", "disabled", "title", "tabindex"}
            if (attrs.get("type") or "").lower() != "checkbox" or any(
                key not in allowed and not key.startswith("aria-") for key in attrs
            ):
                self.errors.append("Only plain checklist checkboxes are allowed; no name/form/action/src/events")
        for key, value in pairs:
            value = value or ""
            if key.startswith("on") or key in ("srcset", "ping", "srcdoc", "background"):
                self.errors.append(f"Active/external attribute forbidden: {key}")
            if key == "src" and tag != "img":
                self.errors.append(f"Unexpected asset src on {tag}")
            if key in ("href", "xlink:href"):
                link = value.strip()
                if not link.startswith("#") and not (tag == "a" and link.startswith(("https://", "http://", "mailto:"))):
                    self.errors.append(f"Non-citation external/local href on {tag}")
            if key == "style" or re.search(r"url\s*\(", value, re.I):
                # SVG presentation attributes can load assets too (fill/filter/etc.).
                self.css.append(value)
        if tag == "html":
            self.lang = bool(attrs.get("lang"))
        if tag == "meta" and attrs.get("name", "").lower() == "viewport":
            self.viewport = "width=device-width" in attrs.get("content", "").replace(" ", "")
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
            self.errors.append("Meta refresh forbidden")
        ident = attrs.get("id")
        if ident:
            if ident in self.ids:
                self.errors.append(f"Duplicate id: {ident}")
            self.ids[ident] = len(self.nodes)
        ancestors = [node[1].get("id") for node in self.stack]
        if not self.days:
            if "data-day" in attrs:
                if not self.top_closed:
                    self.errors.append("First itinerary day must follow the closed #top block")
                # Only still-open neutral layout wrappers may precede day one.
                # Content/text is checked separately; no CSS visibility inference.
                if any(tag_before not in ("div", "main", "section") or not any(
                    attrs_before is parent_attrs for _, parent_attrs in self.stack
                ) for tag_before, attrs_before in self.pre_day_nodes):
                    self.errors.append("Content block inserted between #top and first itinerary day")
            elif self.top_closed:
                self.pre_day_nodes.append((tag, attrs))
        if "data-day" in attrs:
            self.days.append(attrs["data-day"])
            if "itinerary" not in ancestors and ident != "itinerary":
                self.errors.append("Day marker outside itinerary")
        if "data-stop-id" in attrs:
            self.stops.append(attrs["data-stop-id"])
            if "itinerary" not in ancestors:
                self.errors.append("Stop marker outside itinerary")
        if "data-dining-id" in attrs:
            option_id = attrs["data-dining-id"]
            self.dining.append(option_id)
            self.dining_text.setdefault(option_id, [])
            if "itinerary" not in ancestors or not self.days:
                self.errors.append("Dining cards must be inside itinerary after day one begins")
        if ident == "decisions":
            if tag != "details" or "open" in attrs:
                self.errors.append("decisions must be collapsed details")
        if tag == "img":
            attrs["_stop_id"] = next((a.get("data-stop-id") for _, a in reversed(self.stack) if a.get("data-stop-id")), None)
            self.images.append(attrs)
            if not attrs.get("alt", "").strip():
                self.errors.append("Image missing meaningful alt")
        self.nodes.append((tag, attrs))
        if tag not in VOID:
            self.stack.append((tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1][0] != tag:
            self.errors.append(f"Mismatched closing tag: {tag}")
            return
        _, attrs = self.stack.pop()
        if attrs.get("id") == "top":
            self.top_closed = True

    def handle_data(self, data):
        tags = [node[0] for node in self.stack]
        ids = [node[1].get("id") for node in self.stack]
        if "style" in tags:
            self.css.append(data)
            return
        if self.top_closed and not self.days and data.strip():
            self.errors.append("Content text inserted between #top and first itinerary day")
        self.text.append(data)
        for _, attrs in self.stack:
            if "data-dining-id" in attrs:
                self.dining_text[attrs["data-dining-id"]].append(data)
        if "credits" in ids:
            self.credits.append(data)
        if "decisions" in ids:
            self.decisions.append(data)
            if "summary" in tags:
                self.summary.append(data)


def verify(html_path, itinerary, manifest_path, allow_local=False):
    html_path = Path(html_path)
    errors = []
    if html_path.name != "trip.html" or html_path.is_symlink():
        errors.append("Expected actual run-local trip.html, not a symlink")
    text = html_path.read_text(encoding="utf-8-sig")
    if not text.strip():
        errors.append("Report is empty")
    report = Report()
    report.feed(text)
    report.close()
    errors.extend(report.errors)
    if report.stack:
        errors.append("Unclosed HTML elements")
    if not report.lang or not report.viewport:
        errors.append("Missing lang or mobile viewport")
    # Remove CSS comments and escapes so spelling tricks cannot mask remote URLs.
    css = re.sub(r"/\*.*?\*/", "", "\n".join(report.css), flags=re.S)
    css = re.sub(r"\\([0-9a-fA-F]{1,6})\s?", lambda m: chr(int(m[1], 16)) if int(m[1], 16) <= 0x10FFFF else "?", css)
    css = re.sub(r"\\([^\n])", r"\1", css).lower()
    if re.search(r"@import|@font-face|(?:image-set|expression)\s*\(|https?\s*:|file\s*:|(?:^|[^\w])//", css):
        errors.append("External/active CSS forbidden")
    for url in re.findall(r"url\s*\((.*?)\)", css, flags=re.S):
        if not url.strip(" \t\r\n\"'").startswith("#"):
            errors.append("CSS assets forbidden (inline SVG fragments only)")
    if not re.search(r"@media[^{}]*\bprint\b", css):
        errors.append("Missing print stylesheet")
    if not any(font in css for font in ("sans-serif", "serif")):
        errors.append("Missing system font fallback")
    required = ["top", "itinerary", "prep", "credits"]
    if itinerary.get("open_questions"):
        required.insert(2, "decisions")
    elif "decisions" in report.ids:
        errors.append("No unresolved choices: omit decisions section")
    if any(key not in report.ids for key in required):
        errors.append("Missing required section IDs")
    else:
        indices = [report.ids[key] for key in required]
        if indices != sorted(indices):
            errors.append("Sections out of order")
    if "decisions" in report.ids:
        summary = " ".join(report.summary).strip()
        counts = re.findall(r"\d+", summary)
        if str(len(itinerary.get("open_questions", []))) not in counts or not re.search(r"[^\W\d_]", summary):
            errors.append("Decisions summary needs the actual choice count and meaningful text")
        if re.search(r"\bP[012](?:\b|-)|open_questions|evidence\.json|critique\.md|\bAPI\b|Overpass|Open-Meteo", " ".join(report.decisions), re.I):
            errors.append("Source/audit jargon in decisions")
    expected_days = [day["date"] for day in itinerary["days"]]
    stops = [stop for day in itinerary["days"] for stop in day["stops"]]
    if report.days != expected_days:
        errors.append("Rendered day markers do not match itinerary order")
    if report.stops != [stop["id"] for stop in stops]:
        errors.append("Rendered stop markers missing/duplicated/extra or out of order")
    body_text = " ".join(report.text)
    for stop in stops:
        if stop["name"] not in body_text:
            errors.append(f"Stop name missing from readable content: {stop['id']}")
    options = itinerary.get("dining_options", [])
    expected_dining = [option["id"] for option in options]
    if len(report.dining) != len(set(report.dining)) or set(report.dining) != set(expected_dining):
        errors.append("Dining option markers missing/duplicated/extra")
    for option in options:
        if option["name"] not in " ".join(report.dining_text.get(option["id"], [])):
            errors.append(f"Dining venue name missing from its choice card: {option['id']}")
    if re.search(r"\{\{.*?\}\}|\bTODO\b|PLACEHOLDER|待填充", body_text, re.I):
        errors.append("Unfilled shell content")
    _, allowed = manifest_images(html_path, manifest_path)
    if not allowed and report.images:
        errors.append("No-photo/empty manifest: img elements forbidden, including placeholders")
    embedded = {}
    for path, entry in allowed.values():
        embedded.setdefault(data_uri(path), []).append(entry)
    used = set()
    for image in report.images:
        src = image.get("src", "")
        if allow_local and src in allowed:
            entry = allowed[src][1]
        elif src in embedded:
            candidates = embedded[src]
            entry = next((e for e in candidates if e["stop_id"] == image.get("_stop_id")), candidates[0])
        else:
            errors.append("Image is not an authorized inline raster" + (" or local manifest src" if allow_local else ""))
            continue
        used.add(entry["src"])
        if image.get("_stop_id") != entry["stop_id"]:
            errors.append("Image displayed under a different stop than its confirmed identity")
        if entry["stop_id"] not in {stop["id"] for stop in stops}:
            errors.append("Image refers to an absent stop")
        credits = " ".join(report.credits)
        if entry["licence"] not in credits or (entry.get("author") and entry["author"] not in credits):
            errors.append("Missing image author/licence in credits")
        if entry["page"] not in text:
            errors.append("Missing image source-page attribution")
        if entry.get("attribution") and entry["attribution"] not in credits:
            errors.append("Missing required image attribution text")
        if entry.get("licence_url") and entry["licence_url"] not in text:
            errors.append("Missing image licence link")
    if used != set(allowed):
        errors.append("Successful manifest photos omitted from report")
    if re.search(r'''src\s*=\s*["']images/''', text, re.I) and not allow_local:
        errors.append("Local image reference remains; parent embedding required")
    return {"status": "FAIL" if errors else ("PRE_EMBED_OK" if allow_local else "STATIC_CHECKS_OK"),
            "errors": list(dict.fromkeys(errors)), "bytes": html_path.stat().st_size,
            "days": len(report.days), "stops": len(report.stops),
            "outings": sum(stop.get("kind") == "outing" for stop in stops),
            "images": len(report.images), "dining_options": len(report.dining),
            "unknown_markers": body_text.count("待确认"),
            "limitations": "Static parsing only; no browser/layout, source truth, route geometry or live feasibility verification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("--itinerary", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--allow-local-images", action="store_true")
    args = parser.parse_args()
    try:
        itinerary = json.loads(args.itinerary.read_text(encoding="utf-8-sig"))
        result = verify(args.html, itinerary, args.manifest, args.allow_local_images)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(json.dumps({"input_error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
