"""Photo acquisition is entirely mocked; fixtures are not real travel evidence."""
import base64
import copy
from email.message import Message
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from test_workflow import SKILL, fixtures, sample_html
import acquire_images as acquire
from embed_images import embed
from image_assets import manifest_images, safe_path
from validate_itinerary import validate
from verify_report import verify

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j6N8AAAAASUVORK5CYII=")
MEDIA = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Fixture.png"
PAGE = "https://commons.wikimedia.org/wiki/File:Fixture.png"
LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"
TRACKING = "utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content="
# Exact URL shapes observed in imageinfo; bytes/identity metadata remain offline fixtures.
LIVE_PATHS = ("b/ba/Jimei_-_Longzhou_Pool_-_DSCF9278.JPG",
              "1/10/Gardens_read_extensively_park_in_Xiamen.jpg")
THUMB = "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Fixture.png/960px-Fixture.png"
JPEG = b"\xff\xd8\xff" + b"mock JPEG signature fixture"


def metadata():
    return {"query": {"pages": {"1": {"title": "File:Fixture.png", "imageinfo": [{
        "url": MEDIA, "thumburl": MEDIA, "descriptionurl": PAGE, "mime": "image/png",
        "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "LicenseUrl": {"value": LICENSE},
                        "Artist": {"value": "<a>Fixture author</a>"},
                        "Attribution": {"value": "Fixture attribution"}}}]}}}}


class Response(io.BytesIO):
    def __init__(self, url, content=PNG, mime="image/png", length=None, status=200):
        super().__init__(content)
        self.url, self.status = url, status
        self.headers = Message()
        self.headers["Content-Type"] = mime
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def geturl(self):
        return self.url


class NetworkBoundaryTests(unittest.TestCase):
    def response(self, **kwargs):
        return Response(MEDIA, **kwargs)

    def fetch_response(self, response, limit=acquire.MAX_IMAGE_BYTES):
        with patch.object(acquire, "build_opener") as factory:
            factory.return_value.open.return_value = response
            result = acquire.fetch(MEDIA, limit)
            self.assertEqual(factory.return_value.open.call_args.kwargs["timeout"], 15)
            return result

    def test_normal_real_fetch_code_with_mocked_response(self):
        self.assertEqual(self.fetch_response(self.response(length=len(PNG))), (PNG, "image/png"))

    def test_https_host_path_allowlist_blocks_before_open(self):
        urls = ["http://upload.wikimedia.org/wikipedia/commons/a.png", "file:///secret.png",
                "https://127.0.0.1/x.png", "https://upload.wikimedia.org.evil.test/a.png",
                "https://upload.wikimedia.org:443/wikipedia/commons/a.png",
                "https://user@upload.wikimedia.org/wikipedia/commons/a.png",
                "https://upload.wikimedia.org/other/a.png", MEDIA + "?redirect=http://localhost",
                MEDIA + "#fragment", "https://upload.wikimedia.org/wikipedia/commons/%2e%2e/a.png",
                "https://upload.wikimedia.org/wikipedia/commons/%5csecret", "//server/share/a.png"]
        for url in urls:
            with self.subTest(url=url), patch.object(acquire, "build_opener") as factory:
                with self.assertRaises(ValueError):
                    acquire.fetch(url, 100)
                factory.assert_not_called()
        with self.assertRaises(ValueError):
            acquire.checked_url("https://commons.wikimedia.org/wiki/File:A.png", api=True)

    def test_current_imageinfo_urls_normalize_before_request(self):
        for path in LIVE_PATHS:
            original = "https://upload.wikimedia.org/wikipedia/commons/" + path
            thumbnail = "https://thumb.wikimedia.org/wikipedia/commons/thumb/" + path + "/960px-" + path.split("/")[-1]
            for url, kind in ((original, "original"), (thumbnail, "thumbnail")):
                with self.subTest(url=url), patch.object(acquire, "build_opener") as factory:
                    tracked = url + "?" + TRACKING + kind
                    self.assertEqual(acquire.checked_url(tracked), url)
                    factory.return_value.open.return_value = Response(url, JPEG, "image/jpeg")
                    self.assertEqual(acquire.fetch(tracked, 100), (JPEG, "image/jpeg"))
                    self.assertEqual(factory.return_value.open.call_args.args[0].full_url, url)
                    proxy = factory.call_args.args[0]
                    self.assertEqual(proxy.proxies, {})
        legacy = MEDIA.replace("/commons/", "/commons/thumb/")
        self.assertEqual(acquire.checked_url(legacy), legacy)
        self.assertEqual(acquire.checked_url(legacy + "?" + TRACKING + "thumbnail"), legacy)

    def test_tracking_and_thumbnail_bypasses_rejected_before_open(self):
        bad_queries = ["", "token=secret", TRACKING + "thumbnail&token=secret",
                       TRACKING + "thumbnail&utm_source=commons.wikimedia.org",
                       TRACKING + "thumbnail&utm_content=original",
                       TRACKING + "thumbnail&", "utm_source=commons.wikimedia.org",
                       TRACKING + "original", TRACKING + "thumbnail_unscaled",
                       TRACKING.replace("imageinfo", "other") + "thumbnail",
                       TRACKING.replace("commons.wikimedia.org", "evil.test") + "thumbnail",
                       TRACKING.replace("utm_source", "%75tm_source") + "thumbnail",
                       TRACKING + "%74humbnail", TRACKING + "thumbnail;token=secret"]
        urls = [THUMB + "?" + query for query in bad_queries]
        urls += [THUMB.replace("thumb.wikimedia.org", host) for host in
                 ("evil.test", "thumb.wikimedia.org.evil.test", "thumb.wikimedia.org:443",
                  "user@thumb.wikimedia.org", "thumb.wikimedia.org.")]
        urls += [THUMB.replace("/commons/thumb/", path) for path in
                 ("/commons/", "/commons/thumbish/", "/commons/%74humb/", "/other/thumb/")]
        urls += [THUMB + suffix for suffix in
                 ("/../secret", "/%2e%2e/secret", "/%252e%252e/secret", "/%2f../secret",
                  "/%5csecret", "/%00", "/%01", "/%7f", "/%0d%0a", "\x7f", "\n", "#", "#fragment")]
        for url in urls:
            with self.subTest(url=url), patch.object(acquire, "build_opener") as factory:
                with self.assertRaises(ValueError):
                    acquire.fetch(url, 100)
                factory.assert_not_called()

    def test_actual_redirect_handler_rejects_every_redirect_without_second_open(self):
        handler = acquire.NoRedirect()
        request = Request(MEDIA)
        for code in (301, 302, 303, 307, 308):
            for target in (MEDIA, "http://127.0.0.1/secret", "file:///secret", "https://evil.test/a"):
                with self.subTest(code=code, target=target):
                    headers = Message()
                    headers["Location"] = target
                    # urllib itself rejects file: before our redirect hook runs.
                    with self.assertRaises((ValueError, HTTPError)):
                        getattr(handler, f"http_error_{code}")(request, io.BytesIO(), code, "Redirect", headers)

    def test_mime_magic_encoding_status_size_and_truncation_failures(self):
        cases = [self.response(mime="image/svg+xml"), self.response(content=b"<svg/>", mime="image/png"),
                 self.response(mime="image/jpeg"), self.response(length=999), self.response(length=0),
                 self.response(length=1), self.response(content=b""), self.response(status=206),
                 Response("https://evil.test/a.png")]
        encoded = self.response()
        encoded.headers["Content-Encoding"] = "gzip"
        cases.append(encoded)
        for response in cases:
            with self.subTest(headers=response.headers, status=response.status), self.assertRaises(ValueError):
                self.fetch_response(response, limit=100)
        with self.assertRaises(ValueError):
            self.fetch_response(self.response(content=PNG + b"x" * 100), limit=100)

    def test_timeout_and_read_deadline(self):
        with patch.object(acquire, "build_opener") as factory:
            factory.return_value.open.side_effect = TimeoutError("mock timeout")
            with self.assertRaisesRegex(ValueError, "mock timeout"):
                acquire.fetch(MEDIA, 100)
        with patch.object(acquire.time, "monotonic", side_effect=[0, 61]):
            with self.assertRaisesRegex(ValueError, "deadline"):
                self.fetch_response(self.response())


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="media-test-", dir=SKILL / "tests")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "images").mkdir()
        (self.root / "research").mkdir()
        self.brief, self.plan, evidence = fixtures()
        self.record = evidence[0]["records"][0]
        self.record["image_candidates"] = [{"id": "photo-1", "commons_title": "File:Fixture.png",
            "identity_note": "Fixture only: description identifies the exact place.",
            "identity_evidence": [{"source_id": "poi-test", "locator": "description", "value": "Fixture place"}]}]
        self.evidence = evidence[0]
        self.requests = {"selections": [{"stop_id": "d1-walk", "candidate_id": "photo-1", "identity_confirmed": True}], "missing": {}}
        self.manifest = self.root / "images/manifest.json"
        self.html = self.root / "trip.html"
        self.meta = metadata()
        self.save()
        for kind in ("poi", "food", "weather"):
            (self.root / f"research/{kind}.json").write_text('{"sources":[],"records":[]}', encoding="utf-8")

    def save(self):
        for path, value in (("itinerary.json", self.plan), ("evidence.json", self.evidence), ("images/requests.json", self.requests)):
            (self.root / path).write_text(json.dumps(value), encoding="utf-8")

    def run_mocked(self, content=PNG, mime="image/png"):
        self.save()
        self.urls = []
        # Exercise actual URL/type/size reader with mocked HTTP responses, not download stubs.
        def open_response(request, timeout):
            url = request.full_url
            self.urls.append(url)
            if url.startswith("https://commons.wikimedia.org/w/api.php?"):
                return Response(url, json.dumps(self.meta).encode(), "application/json")
            return Response(url, content, mime)
        with patch.object(acquire, "build_opener") as factory:
            factory.return_value.open.side_effect = open_response
            result = acquire.acquire(self.root)
            self.calls = factory.return_value.open.call_count
        return result, json.loads(self.manifest.read_text(encoding="utf-8"))

    def test_success_parent_download_embed_and_final_verify(self):
        result, manifest = self.run_mocked()
        self.assertEqual(result["images"], 1)
        self.assertEqual(self.calls, 2)
        self.assertEqual(len(manifest["attempts"]), 2)
        self.assertTrue(all(a["status"] == "ok" for a in manifest["attempts"]))
        entry = manifest["images"][0]
        self.assertEqual(entry["original_url"], MEDIA)
        self.assertEqual(entry["author"], "Fixture author")
        self.assertTrue(entry["identity_confirmed"])
        image = f'<img src="{entry["src"]}" alt="测试海岸片区">'
        credit = f'Fixture author · Fixture attribution · CC BY-SA 4.0 <a href="{PAGE}">File</a> <a href="{LICENSE}">Licence</a>'
        self.html.write_text(sample_html(image=image, credit=credit), encoding="utf-8")
        self.assertEqual(verify(self.html, self.plan, self.manifest, True)["errors"], [])
        self.assertEqual(embed(self.html, self.manifest)["embedded"], 1)
        self.assertEqual(verify(self.html, self.plan, self.manifest)["errors"], [])
        self.assertIn("data:image/png;base64,", self.html.read_text(encoding="utf-8"))
        self.assertFalse(list((self.root / "images").glob(".preview-*")))
        # Repeat runs preserve existing successful photos without network requests.
        with patch.object(acquire, "fetch") as fetch:
            self.assertEqual(acquire.acquire(self.root)["images"], 1)
            fetch.assert_not_called()

    def test_tracked_live_urls_pipeline_preserves_provenance_and_mime_fallback(self):
        for path in LIVE_PATHS:
            for thumbmime in ("absent", None, "", "image/jpeg"):
                with self.subTest(path=path, thumbmime=thumbmime):
                    self.manifest.unlink(missing_ok=True)
                    self.meta = metadata()
                    page = self.meta["query"]["pages"]["1"]
                    title = "File:" + path.split("/")[-1].replace("_", " ")
                    page["title"] = title
                    self.record["image_candidates"][0]["commons_title"] = title
                    info = page["imageinfo"][0]
                    original = "https://upload.wikimedia.org/wikipedia/commons/" + path
                    thumbnail = "https://thumb.wikimedia.org/wikipedia/commons/thumb/" + path + "/960px-" + path.split("/")[-1]
                    info.update(url=original + "?" + TRACKING + "original",
                                thumburl=thumbnail + "?" + TRACKING + "thumbnail", mime="image/jpeg",
                                descriptionurl="https://commons.wikimedia.org/wiki/" + title.replace(" ", "_"))
                    if thumbmime != "absent":
                        info["thumbmime"] = thumbmime
                    result, manifest = self.run_mocked(JPEG, "image/jpeg")
                    self.assertEqual(result["images"], 1)
                    entry = manifest["images"][0]
                    self.assertEqual(entry["original_url"], info["url"])
                    self.assertEqual(entry["thumbnail_url"], info["thumburl"])
                    self.assertEqual(entry["fetch_url"], thumbnail)
                    self.assertEqual(self.urls, [entry["api_url"], thumbnail])
                    self.assertEqual(manifest["attempts"][-1]["url"], thumbnail)
                    self.assertEqual((self.root / entry["src"]).read_bytes(), JPEG)

    def test_tracked_original_used_when_no_thumbnail(self):
        info = self.meta["query"]["pages"]["1"]["imageinfo"][0]
        info["url"] = MEDIA + "?" + TRACKING + "original"
        info.pop("thumburl")
        result, manifest = self.run_mocked()
        self.assertEqual(result["images"], 1)
        entry = manifest["images"][0]
        self.assertEqual(entry["original_url"], info["url"])
        self.assertEqual(entry["thumbnail_url"], info["url"])
        self.assertEqual(entry["fetch_url"], MEDIA)
        self.assertEqual(self.urls[-1], MEDIA)

    def test_mime_fallback_does_not_bypass_signature_or_explicit_mismatch(self):
        for thumbmime, content, mime in ((None, b"<svg/>", "image/png"),
                                       ("", JPEG, "image/jpeg"),
                                       ("image/jpeg", PNG, "image/png"),
                                       (False, PNG, "image/png")):
            with self.subTest(thumbmime=thumbmime, mime=mime):
                info = self.meta["query"]["pages"]["1"]["imageinfo"][0]
                info.update(thumburl=THUMB + "?" + TRACKING + "thumbnail", thumbmime=thumbmime)
                result, manifest = self.run_mocked(content, mime)
                self.assertEqual(result["images"], 0)
                self.assertTrue(manifest["errors"])
                self.assertFalse(list((self.root / "images").glob("preview-*")))

    def test_invalid_original_or_thumbnail_query_stops_pipeline_before_media(self):
        for field in ("url", "thumburl"):
            with self.subTest(field=field):
                self.meta = metadata()
                self.meta["query"]["pages"]["1"]["imageinfo"][0][field] = MEDIA + "?token=private"
                result, manifest = self.run_mocked()
                self.assertEqual(result["images"], 0)
                self.assertEqual(self.calls, 1)
                self.assertTrue(manifest["errors"])

    def test_partial_missing_option_preserves_success_and_scopes_reason(self):
        alternate = copy.deepcopy(self.plan["days"][0]["stops"][0])
        alternate.update(id="d1-alternative", optional=True)
        self.plan["days"][0]["stops"].append(alternate)
        self.requests["missing"][alternate["id"]] = "Attempted place page lacked a confirmed image"
        _, manifest = self.run_mocked()
        self.assertEqual(manifest["mode"], "local_photos")
        self.assertEqual(len(manifest["images"]), 1)
        self.assertEqual(manifest["missing"], [{"stop_id": "d1-alternative", "reason": self.requests["missing"][alternate["id"]]}])

    def test_failed_candidate_does_not_erase_success(self):
        alternate = copy.deepcopy(self.plan["days"][0]["stops"][0])
        alternate["id"] = "d1-alternative"
        self.plan["days"][0]["stops"].append(alternate)
        self.requests["selections"].append({"stop_id": alternate["id"], "candidate_id": "absent", "identity_confirmed": True})
        _, manifest = self.run_mocked()
        self.assertEqual(len(manifest["images"]), 1)
        self.assertEqual(manifest["errors"][0]["stop_id"], "d1-alternative")

    def test_unconfirmed_or_unsourced_identity_never_downloads(self):
        for mutation in ("confirm", "candidate", "support", "failed-source", "svg"):
            with self.subTest(mutation=mutation):
                orig_req, orig_evidence = copy.deepcopy(self.requests), copy.deepcopy(self.evidence)
                if mutation == "confirm": self.requests["selections"][0]["identity_confirmed"] = False
                if mutation == "candidate": self.requests["selections"][0]["candidate_id"] = "unknown"
                if mutation == "support": self.record["image_candidates"][0]["identity_evidence"] = []
                if mutation == "failed-source": self.evidence["sources"][0]["status"] = "failed"
                if mutation == "svg": self.record["image_candidates"][0]["commons_title"] = "File:Fixture.svg"
                result, manifest = self.run_mocked()
                self.assertEqual(result["images"], 0)
                self.assertEqual(self.calls, 0)
                self.assertTrue(manifest["errors"])
                self.requests, self.evidence = orig_req, orig_evidence
                self.record = self.evidence["records"][0]

    def test_bad_metadata_licence_title_original_mime_and_remote_thumbnail_omitted(self):
        for field, value in (("licence", "All rights reserved"), ("title", "File:Wrong.png"),
                             ("mime", "image/svg+xml"), ("thumburl", "https://127.0.0.1/a.png"),
                             ("descriptionurl", "https://commons.wikimedia.org/wiki/File:Wrong.png")):
            with self.subTest(field=field):
                self.meta = metadata()
                page = self.meta["query"]["pages"]["1"]
                info = page["imageinfo"][0]
                if field == "licence": info["extmetadata"]["LicenseShortName"]["value"] = value
                elif field == "title": page[field] = value
                else: info[field] = value
                result, manifest = self.run_mocked()
                self.assertEqual(result["images"], 0)
                self.assertEqual(self.calls, 1)
                self.assertEqual(manifest["mode"], "no_photos")

    def test_network_failure_attempt_retains_url_time_and_error(self):
        with patch.object(acquire, "fetch", side_effect=ValueError("mock timeout")):
            acquire.acquire(self.root)
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["attempts"][0]["status"], "failed")
        self.assertIn("https://commons.wikimedia.org/w/api.php?", data["attempts"][0]["url"])
        self.assertTrue(data["attempts"][0]["retrieved_at"])
        self.assertIn("mock timeout", data["errors"][0]["error"])
        _, recovered = self.run_mocked()
        self.assertEqual(len(recovered["images"]), 1)
        self.assertEqual(recovered["attempts"][:len(data["attempts"])], data["attempts"])
        self.assertEqual(recovered["errors"], data["errors"])
        with patch.object(acquire, "fetch") as fetch:
            acquire.acquire(self.root)
            fetch.assert_not_called()
        retained = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(retained["attempts"], recovered["attempts"])
        self.assertEqual(retained["errors"], recovered["errors"])

    def test_selection_count_duplicate_absent_and_unsafe_id_rejected(self):
        for selections in ([self.requests["selections"][0]] * 13,
                           [self.requests["selections"][0]] * 2,
                           [{"stop_id": "absent"}], [{"stop_id": "../secret"}]):
            with self.subTest(selections=selections):
                self.requests["selections"] = selections
                self.save()
                with patch.object(acquire, "fetch") as fetch, self.assertRaises(ValueError):
                    acquire.acquire(self.root)
                fetch.assert_not_called()

    def test_missing_reason_required_and_case_collisions_rejected(self):
        self.requests["selections"] = []
        self.save()
        with self.assertRaisesRegex(ValueError, "coverage reason"):
            acquire.acquire(self.root)
        self.requests["missing"] = {"d1-walk": "No image source access in this run; capability recorded"}
        _, manifest = self.run_mocked()
        self.assertEqual(self.calls, 0)
        self.assertEqual(manifest["mode"], "no_photos")
        other = copy.deepcopy(self.plan["days"][0]["stops"][0])
        other["id"] = "D1-WALK"
        self.plan["days"][0]["stops"].append(other)
        self.requests["selections"] = [{"stop_id": "d1-walk"}, {"stop_id": "D1-WALK"}]
        self.save()
        with self.assertRaisesRegex(ValueError, "case-insensitive"):
            acquire.acquire(self.root)

    def test_successful_photo_must_render_at_its_stop_with_full_credits(self):
        _, manifest = self.run_mocked()
        entry = manifest["images"][0]
        image = f'<img src="{entry["src"]}" alt="测试海岸片区">'
        credit = f'Fixture author Fixture attribution CC BY-SA 4.0 <a href="{PAGE}">File</a><a href="{LICENSE}">Licence</a>'
        cases = [sample_html(credit=credit),
                 sample_html(image=image, credit=credit).replace('data-stop-id="d1-walk"', 'data-stop-id="other"'),
                 sample_html(image=image, credit=credit.replace("Fixture attribution", "")),
                 sample_html(image=image, credit=credit.replace(LICENSE, "https://example.org"))]
        for html in cases:
            self.html.write_text(html, encoding="utf-8")
            self.assertTrue(verify(self.html, self.plan, self.manifest, True)["errors"])

    def test_total_size_failure_and_atomic_replace_failure_leave_no_partial_files(self):
        with patch.object(acquire, "MAX_TOTAL_BYTES", 1):
            _, manifest = self.run_mocked()
        self.assertEqual(manifest["images"], [])
        self.assertFalse(list((self.root / "images").glob("*.png")))
        target = self.root / "images/test.png"
        target.write_bytes(b"before")
        with patch.object(acquire.os, "replace", side_effect=OSError("mock replace failure")):
            with self.assertRaises(OSError):
                acquire.atomic_write(target, PNG)
        self.assertEqual(target.read_bytes(), b"before")
        self.assertFalse(list((self.root / "images").glob(".preview-*")))

    def test_symlink_junction_and_resolved_escape_rejected(self):
        for attribute in ("is_symlink", "is_junction"):
            original = getattr(Path, attribute, lambda p: False)
            with self.subTest(attribute=attribute), patch.object(Path, attribute, lambda p: p == self.root / "images" or original(p), create=True):
                with self.assertRaises(ValueError): acquire.acquire(self.root)
                with self.assertRaises(ValueError): safe_path(self.root / "images/a.png")
        original = Path.resolve
        with patch.object(Path, "resolve", lambda p, *a, **kw: self.root / "outside" if p == self.root / "images" else original(p, *a, **kw)):
            with self.assertRaises(ValueError): acquire.acquire(self.root)

    def test_conflicting_source_records_rejected_before_network(self):
        conflict = copy.deepcopy(self.record)
        conflict["name"] = "Another identity"
        self.evidence["records"].append(conflict)
        self.save()
        with patch.object(acquire, "fetch") as fetch, self.assertRaisesRegex(ValueError, "Conflicting"):
            acquire.acquire(self.root)
        fetch.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows UNC boundary")
    def test_unc_paths_rejected_before_filesystem_probe(self):
        with patch.object(Path, "is_symlink") as probe:
            with self.assertRaisesRegex(ValueError, "UNC"):
                safe_path("//fixture-server/fixture-share/run")
            probe.assert_not_called()

    def test_cli_help_and_invalid_input_no_network(self):
        command = [sys.executable, "-B", str(SKILL / "scripts/acquire_images.py")]
        self.assertEqual(subprocess.run(command + ["--help"], capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(command + ["--run-dir", str(self.root / "absent")], capture_output=True).returncode, 2)


class DiningTests(unittest.TestCase):
    def setUp(self):
        self.brief, self.plan, self.evidence = fixtures()
        self.option = {"id": "food-choice-1", "record_id": "food-1", "name": "Fixture restaurant",
            "area": "Fixture area", "address": None, "cuisine": None, "specialties": None, "budget": None,
            "optional": True, "why": "Proposed choice near the walk", "use_with_stop_ids": ["d1-walk"],
            "meal_suggestions": ["Optional lunch"], "operating_caveats": ["Recheck current opening"],
            "chain_fallback": False, "sources": ["poi-test"], "fact_sources": {}}
        for field in ("name", "area"):
            self.option["fact_sources"][field] = [{"source_id": "poi-test", "locator": field, "value": self.option[field]}]
        self.evidence[0]["records"].append({"id": "food-1", "category": "food", "name": self.option["name"]})
        self.plan.update(dining_options=[self.option], dining_coverage_reason="Only one source-backed candidate; others unavailable")

    def check(self):
        return validate(self.plan, self.brief, self.evidence)

    def test_optional_dining_covers_interest_not_outing_or_must_see(self):
        self.brief["interests"].append("Dining")
        self.plan["goal_coverage"].append({"goal": "Dining", "status": "covered", "stop_ids": [], "dining_option_ids": [self.option["id"]]})
        self.assertEqual(self.check()["structural_errors"], [])
        self.assertEqual(self.check()["goal_errors"], [])
        self.assertEqual(self.check()["outing_count"], 1)
        self.brief["must_see"] = ["Dining"]
        self.assertTrue(any("Must-see" in e for e in self.check()["goal_errors"]))
        self.plan["days"][0]["stops"] = []
        self.assertTrue(any("No outing" in e for e in self.check()["goal_errors"]))

    def test_invalid_refs_duplicate_records_names_and_unsourced_facts_fail(self):
        for key, value in (("record_id", "absent"), ("use_with_stop_ids", ["absent"]),
                           ("use_with_stop_ids", ["d1-walk", "d1-walk"]), ("sources", ["failed"]),
                           ("name", "Anonymous"), ("budget", "cheap"), ("specialties", ["invented"]),
                           ("optional", False), ("chain_fallback", None)):
            with self.subTest(key=key, value=value):
                old = self.option[key]
                self.option[key] = value
                self.assertTrue(self.check()["structural_errors"])
                self.option[key] = old
        self.plan["dining_options"].append(copy.deepcopy(self.option))
        self.assertTrue(any("duplicate" in e for e in self.check()["structural_errors"]))

    def test_shortlist_gap_reason_and_backcompat(self):
        self.plan.pop("dining_coverage_reason")
        self.assertTrue(self.check()["structural_errors"])
        self.plan["dining_options"] = []
        self.assertTrue(self.check()["structural_errors"])
        self.plan["dining_coverage_reason"] = "Non-map sources attempted; no verified venues"
        self.assertEqual(self.check()["structural_errors"], [])
        self.plan.pop("dining_options")
        self.assertEqual(self.check()["structural_errors"], [])

    def test_dining_cards_must_be_named_once_inside_itinerary_after_day1(self):
        with tempfile.TemporaryDirectory(prefix="dining-test-", dir=SKILL / "tests") as temp:
            root = Path(temp)
            (root / "images").mkdir()
            manifest = root / "images/manifest.json"
            manifest.write_text('{"mode":"no_photos","images":[]}', encoding="utf-8")
            html = root / "trip.html"
            card = '<article data-dining-id="food-choice-1"><h3>Fixture restaurant</h3><p>Optional lunch choice</p></article>'
            good = sample_html().replace('</main>', card + '</main>')
            def check(text):
                html.write_text(text, encoding="utf-8")
                return verify(html, self.plan, manifest)["errors"]
            self.assertEqual(check(good), [])
            for bad in (sample_html(), good.replace(card, card * 2), good.replace("Fixture restaurant", "Generic lunch"),
                        sample_html().replace('</header>', '</header>' + card), sample_html().replace('</main>', '</main>' + card)):
                self.assertTrue(check(bad))


if __name__ == "__main__":
    unittest.main()
