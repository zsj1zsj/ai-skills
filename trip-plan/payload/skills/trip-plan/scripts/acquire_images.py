"""Parent-only, sequential Commons acquisition for identity-reviewed selected stops.

No search or arbitrary URL input. Reads fixed run-local itinerary, evidence and
images/requests.json; writes images/manifest.json and bounded raster files.
"""
import argparse
from datetime import datetime, timezone
from html import unescape
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit, unquote
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request

from image_assets import MAX_IMAGE_BYTES, MAX_TOTAL_BYTES, manifest_images, raster_type, safe_path
from validate_itinerary import load_evidence, load_json

MAX_SELECTIONS = 12
API_LIMIT = 1024 * 1024
TIMEOUT = 15
DEADLINE = 60
LICENSES = {"CC0", "Public domain", "CC BY 2.0", "CC BY 2.5", "CC BY 3.0", "CC BY 4.0",
            "CC BY-SA 2.0", "CC BY-SA 2.5", "CC BY-SA 3.0", "CC BY-SA 4.0"}


def now():
    return datetime.now(timezone.utc).isoformat()


def checked_url(url, api=False):
    """Validate exact endpoints; strip only the complete imageinfo tracking triple."""
    if not isinstance(url, str) or any(ord(c) < 33 or 127 <= ord(c) <= 159 for c in url) or "\\" in url:
        raise ValueError("Invalid HTTPS URL")
    p = urlsplit(url)
    hosts = {"commons.wikimedia.org"} if api else {"upload.wikimedia.org", "thumb.wikimedia.org"}
    if not url.startswith("https://") or p.netloc not in hosts or "#" in url:
        raise ValueError("Only exact HTTPS Wikimedia hosts without ports/userinfo are allowed")
    if api:
        if p.path != "/w/api.php":
            raise ValueError("Only Commons API endpoint is allowed")
    else:
        prefix = "/wikipedia/commons/thumb/" if p.netloc == "thumb.wikimedia.org" else "/wikipedia/commons/"
        if not p.path.startswith(prefix):
            raise ValueError("Only Commons original/thumbnail paths are allowed")
        if "?" in url:
            content = "thumbnail" if p.path.startswith("/wikipedia/commons/thumb/") else "original"
            expected = {"utm_source=commons.wikimedia.org", "utm_campaign=imageinfo", "utm_content=" + content}
            # Compare raw tokens: no duplicates, encoded aliases, partial sets or extra keys.
            tokens = p.query.split("&")
            if len(tokens) != 3 or set(tokens) != expected:
                raise ValueError("Only exact imageinfo tracking parameters are allowed")
            url = url.split("?", 1)[0]
    decoded = unquote(p.path)
    if (re.search(r"%(?:2f|5c|25)", p.path, re.IGNORECASE) or "\\" in decoded
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in decoded)
            or any(x in (".", "..") for x in decoded.split("/"))):
        raise ValueError("Unsafe URL path")
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Fail closed, including redirects to another allowed host. No second request.
        raise ValueError("HTTP redirects are forbidden")


def fetch(url, limit, api=False):
    try:
        return _fetch(url, limit, api)
    except (OSError, ValueError, URLError) as exc:
        raise ValueError(f"{url}: {exc}") from exc


def _fetch(url, limit, api=False):
    url = checked_url(url, api)
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler())
    started = time.monotonic()
    req = Request(url, headers={"User-Agent": "TripPlanPreview/1.0 (public Commons media; bounded parent request)",
                                "Accept-Encoding": "identity"})
    with opener.open(req, timeout=TIMEOUT) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("Unexpected HTTP status or redirected response")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("Encoded responses are forbidden")
        mime = response.headers.get_content_type()
        valid = {"application/json"} if api else {"image/png", "image/jpeg", "image/gif", "image/webp"}
        if mime not in valid:
            raise ValueError("Unsupported response MIME")
        length = response.headers.get("Content-Length")
        if length is not None and not 0 < int(length) <= limit:
            raise ValueError("Response Content-Length exceeds limit or is empty")
        data = bytearray()
        while True:
            # read1 avoids waiting to fill an entire chunk from a slow peer.
            chunk = response.read1(min(65536, limit + 1 - len(data)))
            if time.monotonic() - started > DEADLINE:
                raise ValueError("Response deadline exceeded")
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("Response exceeds byte limit")
        if not data or (length is not None and len(data) != int(length)):
            raise ValueError("Empty or truncated response")
        if not api and raster_type(data)[0] != mime:
            raise ValueError("Raster MIME/signature mismatch")
        return bytes(data), mime


def atomic_write(path, content):
    path = safe_path(path)
    fd, tmp = tempfile.mkstemp(prefix=".preview-", dir=safe_path(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        safe_path(path)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("IDs must be 1-64 ASCII letters/digits/underscore/hyphen")
    return value


def clean(value):
    return unescape(re.sub(r"<[^>]*>", "", str(value))).strip()


def download(candidate, stop, attempts):
    def request(url, limit, api=False):
        attempt = {"stop_id": stop["id"], "url": url, "retrieved_at": now(), "status": "failed"}
        attempts.append(attempt)
        try:
            result = fetch(url, limit, api)
            attempt["status"] = "ok"
            return result
        except (OSError, ValueError, URLError) as exc:
            attempt["error"] = str(exc)
            raise

    title = candidate.get("commons_title", "")
    if not isinstance(title, str) or not title.startswith("File:") or len(title) > 240 or any(c in title for c in "|\r\n\x00"):
        raise ValueError("A single exact Commons File: title is required")
    if Path(title).suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        raise ValueError("Only original raster file titles are allowed; no SVG conversion")
    api_url = "https://commons.wikimedia.org/w/api.php?" + urlencode({
        "action": "query", "format": "json", "prop": "imageinfo", "titles": title,
        "iiprop": "url|mime|extmetadata", "iiurlwidth": 960})
    payload, _ = request(api_url, API_LIMIT, api=True)
    pages = json.loads(payload)["query"]["pages"]
    if len(pages) != 1:
        raise ValueError("Expected one exact Commons file")
    page = next(iter(pages.values()))
    if page.get("title") != title or "missing" in page:
        raise ValueError("Commons title did not match confirmed candidate exactly")
    info = page["imageinfo"][0]
    if info.get("mime") not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
        raise ValueError("Original is not an authorized raster")
    meta = info.get("extmetadata", {})
    licence = clean(meta.get("LicenseShortName", {}).get("value", ""))
    if licence not in LICENSES:
        raise ValueError("Unrecognized free licence; manual review required")
    licence_url = meta.get("LicenseUrl", {}).get("value")
    if not isinstance(licence_url, str) or not licence_url.startswith("https://"):
        raise ValueError("Missing HTTPS licence page")
    page_url = info["descriptionurl"]
    parsed = urlsplit(page_url)
    if parsed.scheme != "https" or parsed.netloc != "commons.wikimedia.org" or unquote(parsed.path) != "/wiki/" + title.replace(" ", "_") or parsed.query or parsed.fragment:
        raise ValueError("Description page does not match exact file identity")
    original = info["url"]
    thumbnail = info.get("thumburl") or original
    checked_url(original)
    fetch_url = checked_url(thumbnail)
    content, mime = request(fetch_url, MAX_IMAGE_BYTES)
    thumbnail_mime = info.get("thumbmime")
    if thumbnail_mime is None or thumbnail_mime == "":
        thumbnail_mime = info["mime"]
    if mime != thumbnail_mime:
        raise ValueError("API/download MIME mismatch")
    _, extension = raster_type(content)
    filename = "preview-" + identifier(stop["id"]) + extension
    return content, {
        "stop_id": stop["id"], "record_id": stop["record_id"], "candidate_id": candidate["id"],
        "status": "ok", "src": "images/" + filename,
        "author": clean(meta.get("Artist", {}).get("value", "")) or None,
        "attribution": clean(meta.get("Attribution", {}).get("value", "")) or None,
        "licence": licence, "licence_url": licence_url, "page": page_url,
        "original_url": original, "thumbnail_url": thumbnail, "fetch_url": fetch_url, "api_url": api_url,
        "retrieved_at": now(), "mime": mime, "bytes": len(content),
        "identity_confirmed": True, "identity_evidence": candidate["identity_evidence"],
        "identity_note": candidate["identity_note"], "commons_title": title,
    }


def acquire(run_dir):
    root = safe_path(run_dir)
    if not root.is_dir():
        raise ValueError("RUN_DIR must exist")
    images = safe_path(root / "images")
    images.mkdir(exist_ok=True)
    # Input paths are fixed, never supplied by a candidate or remote response.
    plan = load_json(safe_path(root / "itinerary.json"))
    requests = load_json(safe_path(images / "requests.json"))
    evidence = load_evidence(root)
    sources, records = {}, {}
    for artifact in evidence:
        for field, index in (("sources", sources), ("records", records)):
            for item in artifact.get(field, []):
                key = item["id"]
                if key in index and index[key] != item:
                    raise ValueError(f"Conflicting {field} ID: {key}")
                index[key] = item
    outings = [x for day in plan["days"] for x in day["stops"] if x.get("kind") == "outing"]
    if len({x["id"].casefold() for x in outings}) != len(outings):
        raise ValueError("Outing IDs must be unique case-insensitively for files")
    stops = {x["id"]: x for x in outings}
    selections = requests.get("selections")
    if not isinstance(selections, list) or len(selections) > MAX_SELECTIONS:
        raise ValueError("selections must be an array with at most 12 entries")
    selected = {}
    for selection in selections:
        sid = identifier(selection["stop_id"])
        if sid not in stops or sid.casefold() in {key.casefold() for key in selected}:
            raise ValueError("Selection refers to absent/duplicate outing (IDs are case-insensitive for files)")
        selected[sid] = selection
    missing_reasons = requests.get("missing", {})
    if not isinstance(missing_reasons, dict):
        raise ValueError("missing must map stop IDs to scoped attempted/unavailable/preference reasons")
    for sid in stops:
        if sid not in selected and (not isinstance(missing_reasons.get(sid), str) or not missing_reasons[sid].strip()):
            raise ValueError(f"Missing explicit photo coverage reason for {sid}")
    entries, attempts, errors = [], [], []
    manifest_path = safe_path(images / "manifest.json")
    if manifest_path.exists():
        prior, allowed = manifest_images(root / "trip.html", manifest_path)
        attempts = list(prior.get("attempts", []))
        errors = list(prior.get("errors", []))
        entries = [entry for _, entry in allowed.values() if entry["stop_id"] in stops
                   and entry.get("record_id") == stops[entry["stop_id"]].get("record_id")]
    total = sum(safe_path(root / entry["src"]).stat().st_size for entry in entries)
    missing = []
    completed = {entry["stop_id"] for entry in entries}
    for sid in [*selected, *(sid for sid in stops if sid not in selected)]:
        stop = stops[sid]
        if sid in completed:
            continue
        selection = selected.get(sid)
        try:
            if selection is None:
                missing.append({"stop_id": sid, "reason": missing_reasons[sid]})
                continue
            if selection.get("identity_confirmed") is not True:
                raise ValueError("Parent identity confirmation required")
            record = records[stop["record_id"]]
            candidates = [c for c in record.get("image_candidates", []) if c.get("id") == selection.get("candidate_id")]
            if len(candidates) != 1:
                raise ValueError("Candidate must resolve uniquely in the stop's source record")
            candidate = candidates[0]
            identifier(candidate["id"])
            support = candidate.get("identity_evidence")
            if not candidate.get("identity_note") or not isinstance(support, list) or not support:
                raise ValueError("Missing semantic identity evidence")
            for ref in support:
                source = sources.get(ref.get("source_id"), {})
                if not ref.get("locator") or not ref.get("value") or source.get("status") not in ("ok", "partial") or not source.get("url") or not source.get("retrieved_at"):
                    raise ValueError("Unresolved identity source evidence")
            content, entry = download(candidate, stop, attempts)
            if total + len(content) > MAX_TOTAL_BYTES:
                raise ValueError("Total image bytes exceed 20 MiB")
            atomic_write(root / entry["src"], content)
            entries.append(entry)
            total += len(content)
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, URLError) as exc:
            missing.append({"stop_id": sid, "reason": str(exc)})
            errors.append({"stop_id": sid, "candidate_id": selection.get("candidate_id") if selection else None,
                           "at": now(), "error": str(exc)})
    manifest = {"version": 2, "mode": "local_photos" if entries else "no_photos", "images": entries,
                "reason": None if entries else "No usable confirmed photos; see scoped missing/errors and source attempts",
                "missing": missing, "errors": errors, "attempts": attempts}
    atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return {"manifest": str(manifest_path), "images": len(entries), "missing": len(missing), "errors": len(errors)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(acquire(args.run_dir), ensure_ascii=False))
        return 0  # Partial/no photos is not a feasibility failure. Inspect manifest.
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({"input_error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
