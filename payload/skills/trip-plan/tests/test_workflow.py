"""Offline fixtures only. Temporary writes stay inside this skill's tests directory."""
import base64
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from validate_itinerary import load_evidence, validate
from verify_report import verify
from embed_images import embed
from image_assets import manifest_images


def fixtures():
    brief = {"version": 2, "confirmed": True, "destination": "测试城市", "start_date": "2027-05-01",
             "end_date": "2027-05-01", "pace": "relaxed", "scope": "regional_guide", "staycation": False,
             "interests": ["海边散步"], "must_see": [], "must_avoid": [], "arrival": {}, "departure": {}}
    source = {"id": "poi-test", "name": "Fixture only", "url": "https://example.org/place",
              "retrieved_at": "2027-04-20T00:00:00Z", "status": "ok", "licence": None,
              "error": None, "coverage": ["identity"]}
    record = {"id": "poi-1", "name": "测试海岸片区", "sources": ["poi-test"]}
    stop = {"id": "d1-walk", "kind": "outing", "name": "测试海岸片区", "record_id": "poi-1",
            "optional": True, "start": "15:00", "duration_min": 60, "schedule_basis": "proposal",
            "lat": None, "lon": None, "coordinate_kind": "unknown", "navigation": False,
            "transport": None, "sources": ["poi-test"], "fact_sources": {}, "opening_hours": None}
    plan = {"version": 2, "trip": {k: brief[k] for k in ("destination", "start_date", "end_date", "pace", "scope")},
            "days": [{"date": "2027-05-01", "theme": "海岸慢游", "stops": [stop]}],
            "goal_coverage": [{"goal": "海边散步", "status": "covered", "stop_ids": ["d1-walk"], "reason": None}],
            "limitations": ["酒店/机场往返时间未核实"], "open_questions": []}
    evidence = [{"sources": [source], "records": [record]}]
    return brief, plan, evidence


def sample_html(decisions="", image="", credit="资料仅作测试。"):
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body {{font-family: "Microsoft YaHei", sans-serif; line-height:1.7;}}
@media print {{body {{color: black;}}}}</style></head><body>
<header id="top"><h1>测试行程</h1></header><main id="itinerary">
<section data-day="2027-05-01"><h2>海岸慢游</h2>
<article data-stop-id="d1-walk"><h3>测试海岸片区</h3><p>建议 15:00，散步 60 分钟，可选。具体入口待确认。</p>{image}</article>
</section></main>{decisions}<section id="prep"><h2>行前准备</h2><p>酒店/机场往返时间未核实。</p></section>
<footer id="credits">{credit}</footer></body></html>'''


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.brief, self.plan, self.evidence = fixtures()
        self.stop = self.plan["days"][0]["stops"][0]

    def check(self):
        return validate(self.plan, self.brief, self.evidence)

    def test_regional_optional_proposal_is_not_full_feasibility(self):
        result = self.check()
        self.assertEqual(result["structural_errors"], [])
        self.assertEqual(result["goal_errors"], [])
        self.assertEqual(result["outing_count"], 1)
        self.assertEqual(result["feasibility"], "NOT_CERTIFIED")
        self.assertTrue(any("regional outings remain" in item for item in result["unverified"]))

    def test_all_hotel_fails_unless_explicit_staycation(self):
        self.stop.update(kind="hotel")
        result = self.check()
        self.assertTrue(any("No outing" in item for item in result["goal_errors"]))
        self.assertTrue(any("Interest" in item for item in result["goal_errors"]))
        self.brief["staycation"] = True
        self.assertEqual(self.check()["goal_errors"], [])

    def test_dining_interest_with_named_meal_and_separate_outing(self):
        self.brief["interests"].append("Dining")
        meal = copy.deepcopy(self.stop)
        meal.update(id="d1-dinner", kind="meal", name="Fixture restaurant", record_id="food-1", start="18:00")
        self.evidence[0]["records"].append({"id": "food-1", "name": "Fixture restaurant", "sources": ["poi-test"]})
        self.plan["days"][0]["stops"].append(meal)
        self.plan["goal_coverage"].append({"goal": "Dining", "status": "covered", "stop_ids": ["d1-dinner"]})
        result = self.check()
        self.assertEqual(result["goal_errors"], [])
        self.assertEqual(result["structural_errors"], [])
        self.assertEqual(result["outing_count"], 1)
        # Interest coverage is not a loophole around the trip-level outing guard.
        self.plan["days"][0]["stops"] = [meal]
        self.brief["interests"] = ["Dining"]
        self.assertTrue(any("No outing" in item for item in self.check()["goal_errors"]))

    def test_generic_or_unsourced_meal_cannot_cover_interest(self):
        self.stop["kind"] = "meal"
        for field in ("record_id", "sources"):
            with self.subTest(field=field):
                original = self.stop.pop(field)
                self.assertTrue(any("Interest" in item for item in self.check()["goal_errors"]))
                self.stop[field] = original
        self.evidence[0]["sources"][0]["status"] = "failed"
        self.assertTrue(any("Interest" in item for item in self.check()["goal_errors"]))

    def test_must_see_cannot_be_covered_by_meal_or_staycation_blocks(self):
        self.brief["must_see"] = ["Museum"]
        self.plan["goal_coverage"].append({"goal": "Museum", "status": "covered", "stop_ids": ["generic"]})
        block = {"id": "generic", "kind": "meal", "name": "Lunch", "optional": False,
                 "start": "12:00", "duration_min": 60, "schedule_basis": "proposal"}
        self.plan["days"][0]["stops"].append(block)
        for staycation in (False, True):
            self.brief["staycation"] = staycation
            for kind in ("meal", "hotel", "rest"):
                with self.subTest(staycation=staycation, kind=kind):
                    block["kind"] = kind
                    self.assertTrue(any("Must-see Museum" in item for item in self.check()["goal_errors"]))
        # Even a named meal is not an outing for a must-see entry.
        block.update(kind="meal", record_id="poi-1", sources=["poi-test"], coordinate_kind="unknown")
        self.assertTrue(any("Must-see Museum" in item for item in self.check()["goal_errors"]))

    def test_empty_stops_fail(self):
        self.plan["days"][0]["stops"] = []
        self.assertTrue(self.check()["goal_errors"])

    def test_excluded_place_name_and_record_alias(self):
        self.brief["must_avoid"] = ["测试海岸"]
        self.assertTrue(any("excluded" in item for item in self.check()["goal_errors"]))
        self.brief["must_avoid"] = ["旧地名"]
        self.evidence[0]["records"][0]["aliases"] = ["旧地名"]
        self.assertTrue(any("excluded" in item for item in self.check()["goal_errors"]))

    def test_missing_must_see_fails(self):
        self.brief["must_see"] = ["博物馆"]
        self.assertTrue(any("博物馆" in item for item in self.check()["goal_errors"]))

    def test_area_centres_allowed_waterbody_navigation_rejected(self):
        ref = {"source_id": "poi-test", "locator": "coordinates", "value": [24.4, 118.1]}
        self.stop.update(lat=24.4, lon=118.1, coordinate_kind="area_center", fact_sources={"coordinates": [ref]})
        self.assertEqual(self.check()["structural_errors"], [])
        self.stop.update(coordinate_kind="waterbody_center", navigation=True)
        self.assertTrue(any("navigation" in item for item in self.check()["structural_errors"]))

    def test_coordinate_ranges_and_fact_provenance(self):
        self.stop.update(lat=99, lon=118.1)
        self.assertTrue(any("coordinates" in item for item in self.check()["structural_errors"]))
        self.stop.update(lat=24.4)
        self.assertTrue(any("fact_sources" in item for item in self.check()["structural_errors"]))

    def test_unsourced_factual_hours_and_transit_fail_not_proposals(self):
        self.stop["opening_hours"] = "09:00-17:00"
        self.stop["transport"] = {"mode": "taxi", "minutes": 12, "basis": "proposal"}
        errors = self.check()["structural_errors"]
        self.assertTrue(any("opening_hours asserted" in item for item in errors))
        self.assertTrue(any("transit time" in item for item in errors))
        self.assertFalse(any("start" in item or "duration" in item for item in errors))

    def test_failed_source_and_dangling_record_rejected(self):
        self.evidence[0]["sources"][0]["status"] = "failed"
        self.stop["record_id"] = "nonexistent"
        errors = self.check()["structural_errors"]
        self.assertTrue(any("failed source" in item for item in errors))
        self.assertTrue(any("record_id" in item for item in errors))

    def test_weather_record_needs_no_poi_fields(self):
        self.evidence.append({"category": "weather", "sources": [], "records": [
            {"id": "weather-seasonal", "date": None, "kind": "seasonal", "summary": "not a forecast"}]})
        self.assertEqual(self.check()["structural_errors"], [])

    def test_date_gaps_and_duplicates(self):
        self.plan["days"].append(copy.deepcopy(self.plan["days"][0]))
        errors = self.check()["structural_errors"]
        self.assertTrue(any("date range" in item for item in errors))
        self.assertTrue(any("duplicate stop" in item for item in errors))

    def test_generic_rest_does_not_get_null_marker_findings(self):
        self.plan["days"][0]["stops"].append({"id": "rest", "kind": "rest", "name": "午休",
            "optional": False, "start": None, "duration_min": None, "schedule_basis": "proposal"})
        result = self.check()
        self.assertEqual(result["structural_errors"], [])
        self.assertFalse(any("/rest" in item for item in result["unverified"]))

    def test_home_landing_not_local_departure(self):
        self.brief["departure"] = {"date": "2027-05-01", "time": "21:00", "time_kind": "landing_home"}
        self.assertTrue(any("not local departure" in item for item in self.check()["unverified"]))

    def test_nonoptional_overlap(self):
        self.stop["optional"] = False
        second = copy.deepcopy(self.stop)
        second.update(id="second", start="15:30")
        self.plan["days"][0]["stops"].append(second)
        self.assertTrue(any("overlap" in item for item in self.check()["goal_errors"]))


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="evidence-test-", dir=SKILL / "tests")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.research = self.root / "research"
        self.research.mkdir()
        self.brief, self.plan, self.evidence = fixtures()
        for category in ("poi", "weather", "food"):
            (self.research / f"{category}.json").write_text(json.dumps({"category": category, "sources": [], "records": []}), encoding="utf-8")
        self.supplement = self.research / "repair-1-poi.json"
        self.supplement.write_text(json.dumps(self.evidence[0]), encoding="utf-8")
        (self.root / "brief.json").write_text(json.dumps(self.brief), encoding="utf-8")
        (self.root / "itinerary.json").write_text(json.dumps(self.plan), encoding="utf-8")
        self.declare(["research/repair-1-poi.json"])

    def declare(self, paths):
        (self.root / "evidence.json").write_text(json.dumps({"sources": [], "records": [], "research_files": paths}), encoding="utf-8")

    def cli(self):
        return subprocess.run([sys.executable, "-B", str(SKILL / "scripts" / "validate_itinerary.py"),
            str(self.root / "itinerary.json"), "--brief", str(self.root / "brief.json"),
            "--evidence-dir", str(self.root)], capture_output=True, text=True, encoding="utf-8")

    def test_allowlisted_supplement_resolves_and_is_deduplicated(self):
        self.declare(["research/poi.json", "research/repair-1-poi.json", "research/repair-1-poi.json"])
        evidence = load_evidence(self.root)
        self.assertEqual(len(evidence), 5)  # index + 3 required + 1 supplement
        self.assertEqual(validate(self.plan, self.brief, evidence)["structural_errors"], [])
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["feasibility"], "NOT_CERTIFIED")

    def test_unlisted_scratch_files_are_not_loaded(self):
        (self.research / "scratch.json").write_text("not json", encoding="utf-8")
        self.assertEqual(self.cli().returncode, 0)
        self.declare([])
        self.assertEqual(len(load_evidence(self.root)), 4)
        result = self.cli()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("record_id" in item for item in json.loads(result.stdout)["structural_errors"]))

    def test_nested_supplement_allowed(self):
        nested = self.research / "repair-1"
        nested.mkdir()
        self.supplement.rename(nested / "poi.json")
        self.declare(["research/repair-1/poi.json"])
        self.assertEqual(self.cli().returncode, 0)

    def test_invalid_missing_traversal_and_outside_paths_rejected(self):
        outside = self.root / "outside.json"
        outside.write_text(json.dumps(self.evidence[0]), encoding="utf-8")
        cases = [None, "research/repair-1-poi.json", [None], [""],
                 ["research/missing.json"], ["research"], ["research/../outside.json"],
                 ["../outside.json"], ["outside.json"], [str(outside)],
                 ["research//repair-1-poi.json"], ["research/./repair-1-poi.json"],
                 ["research\\repair-1-poi.json"], ["research/repair-1-poi.txt"],
                 ["https://example.org/research/a.json"]]
        for declared in cases:
            with self.subTest(declared=declared):
                self.declare(declared)
                with self.assertRaises((ValueError, OSError)):
                    load_evidence(self.root)
                result = self.cli()
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("input_error", json.loads(result.stdout))

    def test_required_files_still_required_and_invalid_json_is_not_skipped(self):
        self.supplement.write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_evidence(self.root)
        self.declare([])
        (self.research / "weather.json").unlink()
        self.assertEqual(self.cli().returncode, 2)

    def test_symlink_and_resolved_escape_guards(self):
        # Simulate path metadata deterministically; no Windows symlink privilege needed.
        original_is_symlink = Path.is_symlink
        for linked in (self.supplement, self.research):
            with self.subTest(linked=linked), patch.object(Path, "is_symlink", lambda p: p == linked or original_is_symlink(p)):
                with self.assertRaises(ValueError):
                    load_evidence(self.root)
        original_resolve = Path.resolve
        outside = self.root / "outside.json"
        with patch.object(Path, "resolve", lambda p, *a, **kw: outside if p == self.supplement else original_resolve(p, *a, **kw)):
            with self.assertRaises(ValueError):
                load_evidence(self.root)


class FilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trip-test-", dir=SKILL / "tests")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.html = self.root / "trip.html"
        self.manifest = self.root / "images" / "manifest.json"
        self.manifest.parent.mkdir()
        self.manifest.write_text(json.dumps({"version": 2, "mode": "no_photos", "images": []}), encoding="utf-8")
        self.brief, self.plan, self.evidence = fixtures()
        self.html.write_text(sample_html(), encoding="utf-8")

    def check(self, html=None, allow_local=False):
        if html is not None:
            self.html.write_text(html, encoding="utf-8")
        return verify(self.html, self.plan, self.manifest, allow_local)

    def image_fixture(self):
        # Actual 1px PNG fixture, never fetched from a source or used as trip evidence.
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j6N8AAAAASUVORK5CYII=")
        (self.manifest.parent / "test.png").write_bytes(png)
        self.entry = {"stop_id": "d1-walk", "status": "ok", "src": "images/test.png", "author": "Test author",
                      "licence": "CC0", "page": "https://example.org/image"}
        self.manifest.write_text(json.dumps({"version": 2, "mode": "local_photos", "images": [self.entry]}), encoding="utf-8")
        self.image = '<figure><img src="images/test.png" alt="测试海岸片区"><figcaption>Test author · CC0</figcaption></figure>'
        self.credit = 'Test author · CC0 <a href="https://example.org/image">测试来源</a>'
        self.html.write_text(sample_html(image=self.image, credit=self.credit), encoding="utf-8")

    def test_no_photos_offline_report_and_noop_embed(self):
        self.assertEqual(self.check()["errors"], [])
        original = self.html.read_bytes()
        self.assertEqual(embed(self.html, self.manifest)["embedded"], 0)
        self.assertEqual(self.html.read_bytes(), original)

    def test_placeholder_img_fails(self):
        self.assertTrue(self.check(sample_html(image='<img src="" alt="placeholder">'))["errors"])

    def test_external_assets_and_active_markup_fail(self):
        snippets = ['<img src="https://example.org/p.png" alt="x">', '<script>alert(1)</script>',
                    '<link rel="stylesheet" href="https://example.org/a.css">',
                    '<svg><image href="https://example.org/a.png"></image></svg>',
                    '<div style="background:url(//example.org/p.png)">x</div>',
                    '<style>@import "local.css";</style>', '<div onclick="x()">x</div>',
                    '<meta http-equiv="refresh" content="1;url=https://example.org">',
                    '<style>body{background:u\\72l(https://example.org/a.png)}</style>',
                    '<style>body{background:image-set("local.png" 1x)}</style>',
                    '<svg><rect fill="url(external.svg#paint)"></rect></svg>']
        for snippet in snippets:
            with self.subTest(snippet=snippet):
                self.assertTrue(self.check(sample_html(image=snippet))["errors"])

    def test_plain_checklist_checkboxes_allowed(self):
        for checkbox in ('<label><input type="checkbox">带雨伞</label>',
                         '<input type="CHECKBOX" id="packed" class="check" checked disabled aria-label="带雨伞"><label for="packed">带雨伞</label>'):
            with self.subTest(checkbox=checkbox):
                html = sample_html().replace('<h2>行前准备</h2>', '<h2>行前准备</h2>' + checkbox)
                self.assertEqual(self.check(html)["errors"], [])

    def test_other_inputs_and_bound_or_active_checkboxes_rejected(self):
        snippets = ['<input type="image" src="https://example.org/a.png">',
                    '<input type="text">', '<input>',
                    '<input type="checkbox" onclick="alert(1)">',
                    '<input type="checkbox" form="booking">',
                    '<input type="checkbox" name="booking">',
                    '<input type="checkbox" formaction="https://example.org">',
                    '<input type="checkbox" src="https://example.org/a.png">',
                    '<form><input type="checkbox"></form>', '<button>submit</button>']
        for snippet in snippets:
            with self.subTest(snippet=snippet):
                self.assertTrue(self.check(sample_html(image=snippet))["errors"])

    def test_preamble_between_title_and_first_day_rejected(self):
        html = sample_html()
        for content in ('<aside><p>Audit preamble</p></aside>', '<p>Summary</p>',
                        '<div>Inline preamble</div>', '<section></section>', 'Loose preamble text'):
            for marker in ('</header>', '<main id="itinerary">'):
                with self.subTest(content=content, marker=marker):
                    errors = self.check(html.replace(marker, marker + content))["errors"]
                    self.assertTrue(any("between #top and first itinerary day" in item for item in errors), errors)

    def test_open_layout_wrappers_comments_and_whitespace_before_day_allowed(self):
        html = sample_html().replace('<main id="itinerary">', '\n<!-- comment -->\n<div class="layout"><main id="itinerary"><div class="days">')
        html = html.replace('</main>', '</div></main></div>')
        self.assertEqual(self.check(html)["errors"], [])

    def test_normal_citation_link_allowed(self):
        self.assertEqual(self.check(sample_html(credit='<a href="https://example.org/source">来源</a>'))["errors"], [])

    def test_decisions_optional_collapsed_and_no_jargon(self):
        self.plan["open_questions"] = [{"question": "怎么选?", "options": [], "recommendation": "A"}]
        good = '<details id="decisions"><summary>需要确认 · 1 项 · 时间选择</summary><p>问题：下午还是晚上？建议下午。</p></details>'
        self.assertEqual(self.check(sample_html(decisions=good))["errors"], [])
        self.assertTrue(self.check(sample_html(decisions=good.replace('<details ', '<details open ')))["errors"])
        self.assertTrue(self.check(sample_html(decisions=good.replace('问题：', 'P1-1 evidence.json 问题：')))["errors"])
        self.plan["open_questions"] = []
        self.assertTrue(self.check(sample_html(decisions=good))["errors"])

    def test_missing_rendered_stops_and_names_fail(self):
        self.assertTrue(self.check(sample_html().replace('data-stop-id="d1-walk"', 'data-stop-id="other"'))["errors"])
        self.assertTrue(self.check(sample_html().replace("测试海岸片区", "其他"))["errors"])

    def test_section_order_and_print_checks(self):
        self.assertTrue(self.check(sample_html().replace('id="top"', 'id="credits"').replace('<footer id="credits"', '<footer id="top"'))["errors"])
        self.assertTrue(self.check(sample_html().replace("@media print", "@media screen"))["errors"])

    def test_local_embed_and_final_verify(self):
        self.image_fixture()
        self.assertEqual(self.check(allow_local=True)["errors"], [])
        self.assertTrue(self.check()["errors"])
        command = [sys.executable, "-B", str(SKILL / "scripts" / "embed_images.py"), str(self.html), "--manifest", str(self.manifest)]
        embedded = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(embedded.returncode, 0, embedded.stdout + embedded.stderr)
        self.assertIn("'embedded': 1", embedded.stdout)
        result = self.check()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["status"], "STATIC_CHECKS_OK")
        self.assertNotIn('src="images/', self.html.read_text(encoding="utf-8"))

    def test_unmanifested_image_no_write(self):
        self.image_fixture()
        self.html.write_text(sample_html(image=self.image.replace("test.png", "other.png")), encoding="utf-8")
        original = self.html.read_bytes()
        with self.assertRaises(ValueError):
            embed(self.html, self.manifest)
        self.assertEqual(self.html.read_bytes(), original)

    def test_path_escape_remote_absolute_and_wrong_type_rejected(self):
        self.image_fixture()
        for src in ("../secret.png", "images/../../secret.png", "https://example.org/x.png", "C:/secret.png",
                    "/secret.png", "images\\test.png", "images/%2e%2e/x.png", "images/test.svg"):
            with self.subTest(src=src):
                self.entry["src"] = src
                self.manifest.write_text(json.dumps({"mode": "local_photos", "images": [self.entry]}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    manifest_images(self.html, self.manifest)

    def test_manifest_outside_run_is_rejected(self):
        outside = self.root / "other-manifest.json"
        outside.write_text(self.manifest.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(ValueError):
            manifest_images(self.html, outside)

    def test_manifest_no_photo_contradiction_and_missing_credits(self):
        self.image_fixture()
        self.manifest.write_text(json.dumps({"mode": "no_photos", "images": [self.entry]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            manifest_images(self.html, self.manifest)
        self.manifest.write_text(json.dumps({"mode": "local_photos", "images": [self.entry]}), encoding="utf-8")
        self.assertTrue(self.check(sample_html(image=self.image), allow_local=True)["errors"])

    def test_nonimage_bytes_rejected_before_write(self):
        self.image_fixture()
        (self.manifest.parent / "test.png").write_text("secret text", encoding="utf-8")
        original = self.html.read_bytes()
        with self.assertRaises(ValueError):
            embed(self.html, self.manifest)
        self.assertEqual(self.html.read_bytes(), original)

    def test_cli_exit_codes_and_actual_file_checks(self):
        brief_path, plan_path = self.root / "brief.json", self.root / "itinerary.json"
        brief_path.write_text(json.dumps(self.brief), encoding="utf-8")
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        (self.root / "evidence.json").write_text(json.dumps(self.evidence[0]), encoding="utf-8")
        (self.root / "research").mkdir()
        for category in ("poi", "weather", "food"):
            (self.root / "research" / f"{category}.json").write_text(json.dumps({"category": category, "sources": [], "records": []}), encoding="utf-8")
        cmd = [sys.executable, "-B", str(SKILL / "scripts" / "validate_itinerary.py"), str(plan_path), "--brief", str(brief_path), "--evidence-dir", str(self.root)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["feasibility"], "NOT_CERTIFIED")
        self.plan["days"][0]["stops"] = []
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 1)
        plan_path.write_text("not json", encoding="utf-8")
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 2)
        _, plan, _ = fixtures()
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        check_cmd = [sys.executable, "-B", str(SKILL / "scripts" / "verify_report.py"), str(self.html), "--itinerary", str(plan_path), "--manifest", str(self.manifest)]
        self.assertEqual(subprocess.run(check_cmd, capture_output=True).returncode, 0)
        self.html.unlink()
        self.assertEqual(subprocess.run(check_cmd, capture_output=True).returncode, 2)


class ContractTests(unittest.TestCase):
    def test_active_contracts_have_no_missing_dependency_paths(self):
        roles = ["researcher", "itinerary-synthesizer", "itinerary-critic", "itinerary-designer", "itinerary-generator"]
        paths = [SKILL / "SKILL.md", SKILL / "references" / "contracts.md"]
        paths += [SKILL.parent.parent / "agents" / f"{role}.md" for role in roles]
        content = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for legacy in (".pi/skills/trip-", "collect_evidence.py", "fetch_images.py", "trip-validate", "trip-images"):
            self.assertNotIn(legacy, content)
        for name in set(re.findall(r"scripts/([a-z_]+\.py)", content)):
            self.assertTrue((SKILL / "scripts" / name).is_file(), name)
        for path in paths[2:]:
            text = path.read_text(encoding="utf-8")
            self.assertIn("model: openai-codex/gpt-6-astra", text)
            self.assertIn("spawning: false", text)
            self.assertIn("contract", text)
            self.assertIn("RUN_DIR", text)

    def test_spawn_names_thinking_and_single_skill_discovery(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for name in ("research-1", "research-2", "research-3", "plan", "review", "ui", "build"):
            self.assertIn(f"<slug>-{name}", skill)
        for level in ("low", "high", "medium"):
            self.assertIn(level, skill)
        self.assertIn("No polling", skill)
        self.assertIn("2 rounds", skill)
        self.assertEqual(list(SKILL.rglob("SKILL.md")), [SKILL / "SKILL.md"])
        # Portable distribution excludes the source computer's historical backups.
        # Runtime structure and single-skill discovery are checked above.


if __name__ == "__main__":
    unittest.main()
