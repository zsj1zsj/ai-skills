"""Structural/goal checks only; never certifies live travel feasibility. Stdlib only."""
import argparse
from datetime import date, timedelta
import json
import math
from pathlib import Path
import re
import sys

from image_assets import safe_path


def load_json(path):
    def invalid(value):
        raise ValueError(f"Non-JSON number: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=invalid)


def load_evidence(run_dir):
    """Read the three required artifacts plus explicit, contained JSON supplements."""
    root = safe_path(run_dir)
    index_path = safe_path(root / "evidence.json")
    if index_path.is_symlink():
        raise ValueError("evidence.json must not be a symlink")
    index = load_json(index_path)
    declared = index.get("research_files", [])
    if not isinstance(declared, list):
        raise ValueError("evidence.research_files must be an array of run-relative paths")
    research = root / "research"
    if research.is_symlink() or research.resolve() != research or not research.is_dir():
        raise ValueError("research must be an existing run-local directory, not a symlink/junction")
    required = [f"research/{kind}.json" for kind in ("poi", "weather", "food")]
    artifacts, seen = [index], set()
    for relative in required + declared:
        if not isinstance(relative, str) or any(c in relative for c in "\\\\:\x00"):
            raise ValueError("Invalid research_files path")
        parts = relative.split("/")
        if len(parts) < 2 or parts[0] != "research" or any(p in ("", ".", "..") for p in parts):
            raise ValueError("research_files paths must remain inside research/ without traversal")
        path = safe_path(root.joinpath(*parts))
        cursor = root
        for part in parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Research artifact symlinks are forbidden")
        resolved = path.resolve()
        if not resolved.is_relative_to(research) or path.suffix.lower() != ".json" or not path.is_file():
            raise ValueError(f"Research artifact must be an existing contained JSON file: {relative}")
        if resolved not in seen:
            artifacts.append(load_json(resolved))
            seen.add(resolved)
    return artifacts


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def normalized(value):
    return re.sub(r"[\W_]", "", str(value).casefold())


def validate(plan, brief, evidence=None):
    structural, goals, unverified = [], [], []
    sources, records = {}, {}
    for artifact in evidence or []:
        for source in artifact.get("sources", []):
            sid = source.get("id")
            if not sid:
                structural.append("Source missing id")
            elif sid in sources and sources[sid] != source:
                structural.append(f"Conflicting source id: {sid}")
            else:
                sources[sid] = source
        for record in artifact.get("records", []):
            rid = record.get("id")
            if not rid:
                structural.append("Evidence record missing id")
            elif rid in records and records[rid] != record:
                structural.append(f"Conflicting record id: {rid}")
            else:
                records[rid] = record

    def refs(values, label):
        if not isinstance(values, list) or not values:
            structural.append(f"{label}: missing source references")
            return
        if evidence is not None:
            for sid in values:
                source = sources.get(sid, {})
                if source.get("status") not in ("ok", "partial"):
                    structural.append(f"{label}: unresolved/failed source {sid}")
                elif not source.get("url") or not source.get("retrieved_at"):
                    structural.append(f"{label}: source {sid} lacks URL/timestamp")

    def fact(obj, field, label):
        support = obj.get("fact_sources", {}).get(field)
        if not isinstance(support, list) or not support:
            structural.append(f"{label}: {field} asserted without fact_sources")
            return
        for ref in support:
            if not isinstance(ref, dict) or not ref.get("locator") or ref.get("value") is None:
                structural.append(f"{label}: invalid fact reference for {field}")
            else:
                refs([ref.get("source_id")], f"{label}.{field}")

    trip = plan.get("trip", {})
    if plan.get("version") != 2 or brief.get("version") != 2:
        structural.append("Expected version 2 plan and brief")
    if brief.get("confirmed") is not True:
        goals.append("Brief has not been confirmed")
    if brief.get("scope") not in ("regional_guide", "door_to_door"):
        structural.append("Unknown brief scope")
    if brief.get("pace") not in ("relaxed", "balanced", "packed"):
        structural.append("Unknown brief pace")
    for field in ("start_date", "end_date", "destination", "scope", "pace"):
        if not brief.get(field) or trip.get(field) != brief.get(field):
            structural.append(f"trip.{field} must match brief")
    try:
        start, end = (date.fromisoformat(brief[k]) for k in ("start_date", "end_date"))
        if end < start or (end - start).days > 366:
            raise ValueError("reversed or longer than 367 days")
        expected = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    except (KeyError, TypeError, ValueError) as exc:
        structural.append(f"Invalid date range: {exc}")
        expected = []
    days = plan.get("days", [])
    if not isinstance(days, list) or not days:
        structural.append("days must be a nonempty array")
        days = []
    if [day.get("date") for day in days] != expected:
        structural.append("days must cover the inclusive date range in order, without gaps/duplicates")
    all_stops, outings = {}, []
    excluded = [normalized(name) for name in brief.get("must_avoid", []) if normalized(name)]
    for day in days:
        stops = day.get("stops", [])
        if not isinstance(stops, list):
            structural.append(f"{day.get('date')}: stops must be an array")
            continue
        prior_place = False
        previous_end = None
        previous_optional = False
        for stop in stops:
            sid = stop.get("id")
            label = f"{day.get('date')}/{sid or '?'}"
            if not isinstance(sid, str) or not sid or sid in all_stops:
                structural.append(f"{label}: missing/duplicate stop id")
            else:
                all_stops[sid] = stop
            for field in ("name", "kind", "optional", "start", "duration_min", "schedule_basis"):
                if field not in stop:
                    structural.append(f"{label}: missing {field}")
            if not isinstance(stop.get("name"), str) or not stop.get("name", "").strip():
                structural.append(f"{label}: empty stop name")
            if stop.get("kind") not in ("outing", "meal", "rest", "hotel", "transfer"):
                structural.append(f"{label}: invalid kind")
            if type(stop.get("optional")) is not bool:
                structural.append(f"{label}: optional must be boolean")
            if stop.get("schedule_basis") != "proposal":
                structural.append(f"{label}: planned starts/durations must be labelled proposal")
            names = [normalized(stop.get("name", ""))] + [normalized(n) for n in stop.get("aliases", [])]
            if evidence is not None and stop.get("record_id") in records:
                rec = records[stop["record_id"]]
                names += [normalized(rec.get("name", ""))] + [normalized(n) for n in rec.get("aliases", [])]
            for avoid in excluded:
                if any(avoid in name for name in names):
                    goals.append(f"{label}: excluded place {avoid}")
            outing = stop.get("kind") == "outing"
            if outing:
                outings.append(stop)
            place = outing or bool(stop.get("record_id"))
            if place:
                refs(stop.get("sources"), label)
                rid = stop.get("record_id")
                if not rid or (evidence is not None and rid not in records):
                    structural.append(f"{label}: unresolved record_id {rid}")
                lat, lon = stop.get("lat"), stop.get("lon")
                if lat is None and lon is None:
                    unverified.append(f"{label}: no coordinates; cannot map exact access")
                elif not (number(lat) and number(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                    structural.append(f"{label}: invalid/partial coordinates")
                else:
                    fact(stop, "coordinates", label)
                kind = stop.get("coordinate_kind")
                if kind not in ("entrance", "area_center", "waterbody_center", "unknown"):
                    structural.append(f"{label}: invalid coordinate_kind")
                if stop.get("navigation") and (kind != "entrance" or lat is None or lon is None):
                    structural.append(f"{label}: navigation requires entrance coordinates, never area/waterbody centres")
                if kind in ("area_center", "waterbody_center"):
                    unverified.append(f"{label}: overview marker, not an exact entry")
                if stop.get("opening_hours") is None and kind != "area_center":
                    unverified.append(f"{label}: access/opening conditions not verified; assess relevance")
                for field in ("opening_hours", "price"):
                    if stop.get(field) is not None:
                        fact(stop, field, label)
                transfer = stop.get("transport")
                if prior_place and transfer is None:
                    unverified.append(f"{label}: inbound transfer unverified")
                prior_place = True
            transfer = stop.get("transport")
            if transfer is not None:
                if transfer.get("mode") not in ("walk", "transit", "taxi", "bike", "train", "ferry", "car"):
                    structural.append(f"{label}: invalid transport mode")
                minutes = transfer.get("minutes")
                if minutes is None:
                    unverified.append(f"{label}: transfer minutes unverified")
                elif not number(minutes) or minutes < 0:
                    structural.append(f"{label}: invalid transport minutes")
                else:
                    if transfer.get("basis") != "verified":
                        structural.append(f"{label}: numerical transit time must be sourced, not invented")
                    fact(transfer, "minutes", label)
            time = stop.get("start")
            duration = stop.get("duration_min")
            start_min = None
            if time is not None:
                if not isinstance(time, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time):
                    structural.append(f"{label}: invalid proposed start")
                else:
                    hour, minute = map(int, time.split(":"))
                    start_min = hour * 60 + minute
            if duration is not None and (not number(duration) or duration <= 0):
                structural.append(f"{label}: invalid proposed duration")
                duration = None
            if outing and (time is None or duration is None):
                unverified.append(f"{label}: flexible/unspecified proposed schedule")
            inbound = transfer.get("minutes") if transfer else None
            if start_min is not None and previous_end is not None and not stop.get("optional") and not previous_optional:
                if start_min < previous_end + (inbound if number(inbound) else 0):
                    goals.append(f"{label}: proposed blocks/known inbound transfer overlap")
            previous_end = start_min + duration if start_min is not None and duration is not None else None
            previous_optional = stop.get("optional", False)
            if previous_end is not None and previous_end > 1440:
                goals.append(f"{label}: proposed block crosses day boundary without explicit next-day handling")
    if not outings and brief.get("staycation") is not True:
        goals.append("No outing candidates: relaxed is not hotel-only; explicit staycation required")
    dining = plan.get("dining_options", [])
    if not isinstance(dining, list):
        structural.append("dining_options must be an array")
        dining = []
    dining_by_id, dining_records, dining_names = {}, set(), set()
    for option in dining:
        if not isinstance(option, dict):
            structural.append("Invalid dining option")
            continue
        oid, rid = option.get("id"), option.get("record_id")
        label = f"dining/{oid or '?'}"
        if not isinstance(oid, str) or not oid or oid in dining_by_id or oid in all_stops:
            structural.append(f"{label}: missing/duplicate dining id")
        else:
            dining_by_id[oid] = option
        name = option.get("name")
        if not isinstance(name, str) or not name.strip() or normalized(name) in dining_names:
            structural.append(f"{label}: missing/duplicate venue name")
        dining_names.add(normalized(name))
        if not isinstance(rid, str) or not rid or rid in dining_records:
            structural.append(f"{label}: missing/duplicate dining record_id")
        else:
            dining_records.add(rid)
        rec = records.get(rid, {})
        if evidence is not None:
            if not rec or rec.get("category") != "food":
                structural.append(f"{label}: unresolved food record_id {rid}")
            elif name not in [rec.get("name"), *rec.get("aliases", [])]:
                structural.append(f"{label}: name does not match food record")
        refs(option.get("sources"), label)
        if option.get("optional") is not True or not option.get("why"):
            structural.append(f"{label}: optional true and itinerary-fit rationale required")
        if type(option.get("chain_fallback")) is not bool:
            structural.append(f"{label}: chain_fallback must be boolean")
        linked = option.get("use_with_stop_ids")
        if not isinstance(linked, list) or not linked or len(linked) != len(set(linked)) or any(s not in all_stops for s in linked):
            structural.append(f"{label}: invalid/duplicate use_with_stop_ids")
        if not option.get("area") or not isinstance(option.get("meal_suggestions"), list) or not option.get("meal_suggestions"):
            structural.append(f"{label}: area and proposed meal connections required")
        if not isinstance(option.get("operating_caveats"), list) or not option.get("operating_caveats"):
            structural.append(f"{label}: operating caveats required")
        for field in ("name", "area", "address", "cuisine", "specialties", "budget", "opening_hours"):
            if option.get(field) is not None:
                fact(option, field, label)
        names = [normalized(name), normalized(rec.get("name", ""))] + [normalized(n) for n in rec.get("aliases", [])]
        if any(avoid in n for avoid in excluded for n in names):
            goals.append(f"{label}: excluded dining venue")
    local_choices = sum(isinstance(option, dict) and option.get("chain_fallback") is False for option in dining)
    if "dining_options" in plan and local_choices < 3 and not plan.get("dining_coverage_reason"):
        structural.append("Below-target dining_options requires dining_coverage_reason; chains do not fill target")
    if "dining_options" not in plan:
        unverified.append("Legacy plan: dining shortlist absent; new runs must provide choices or a coverage reason")
    elif local_choices < 3:
        unverified.append("Dining coverage below ordinary 3-5 target; critic must review sourced coverage reason")
    coverage = {entry.get("goal"): entry for entry in plan.get("goal_coverage", [])}
    for goal in dict.fromkeys(brief.get("interests", []) + brief.get("must_see", [])):
        item = coverage.get(goal, {})
        ids = item.get("stop_ids", [])
        dining_ids = item.get("dining_option_ids", [])
        if not isinstance(dining_ids, list) or len(dining_ids) != len(set(dining_ids)) or any(i not in dining_by_id for i in dining_ids):
            structural.append(f"Goal {goal}: invalid/duplicate dining_option_ids")
            dining_ids = []
        if item.get("status") == "accepted_omission" and item.get("accepted_by_user") is True and item.get("reason"):
            unverified.append(f"Accepted goal omission: {goal} (critic must confirm user acceptance)")
        elif item.get("status") == "covered" and (ids or dining_ids) and all(i in all_stops for i in ids):
            covered_stops = [all_stops[i] for i in ids]
            has_outing = any(stop.get("kind") == "outing" for stop in covered_stops)
            # Interest relevance is a critic judgment, not a language-specific keyword rule.
            named_meal = any(
                stop.get("kind") == "meal" and stop.get("record_id") and stop.get("sources")
                and (evidence is None or (
                    stop["record_id"] in records
                    and all(sources.get(sid, {}).get("status") in ("ok", "partial") for sid in stop["sources"])
                )) for stop in covered_stops
            )
            staycation_activity = brief.get("staycation") is True and any(
                stop.get("kind") in ("rest", "hotel") for stop in covered_stops
            )
            if goal in brief.get("must_see", []):
                if not has_outing:
                    goals.append(f"Must-see {goal} requires outing coverage, not meal/hotel/rest blocks")
            elif not (has_outing or named_meal or dining_ids or staycation_activity):
                goals.append(f"Interest {goal} needs an outing, sourced named meal/dining option, or explicit staycation activity")
        elif goal in brief.get("must_see", []) or not item.get("reason"):
            goals.append(f"Missing/unresolved goal coverage: {goal}")
        else:
            unverified.append(f"Unresolved interest: {goal}: {item['reason']}")
    if trip.get("scope") == "regional_guide":
        unverified.append("Regional guide: hotel/airport door-to-door timing not certified; regional outings remain candidates")
    for field in ("arrival", "departure"):
        boundary = brief.get(field) or {}
        if not boundary.get("date") or not boundary.get("time"):
            unverified.append(f"{field} date/time unknown; boundary transfer feasibility unverified")
    if (brief.get("departure") or {}).get("time_kind") == "landing_home":
        unverified.append("Home landing time is not local departure; final-day boundary unverified")
    if not isinstance(plan.get("limitations"), list) or not isinstance(plan.get("open_questions"), list):
        structural.append("limitations and open_questions must be arrays")
    for question in plan.get("open_questions", []):
        if not isinstance(question, dict) or not question.get("question") or not question.get("options") or not question.get("recommendation"):
            structural.append("open_questions entries must be actual structured choices")
    if evidence is None:
        unverified.append("Source/record resolution not checked: no evidence directory provided")
    # The checker cannot verify source truth, arbitrary constraints, or live operations.
    unverified.append("Live opening/transit/booking feasibility and semantic source support require critic review")
    return {"structural_errors": structural, "goal_errors": goals,
            "unverified": list(dict.fromkeys(unverified)), "outing_count": len(outings),
            "status": "NEEDS_WORK" if structural or goals else "STRUCTURE_GOALS_OK",
            "feasibility": "NOT_CERTIFIED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("itinerary", type=Path)
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    try:
        evidence = None
        if args.evidence_dir:
            evidence = load_evidence(args.evidence_dir)
        result = validate(load_json(args.itinerary), load_json(args.brief), evidence)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(json.dumps({"input_error": str(exc), "feasibility": "NOT_CERTIFIED"}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["structural_errors"] or result["goal_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
