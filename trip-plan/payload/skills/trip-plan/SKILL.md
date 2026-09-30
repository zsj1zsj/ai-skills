---
name: trip-plan
description: >
  Plan a trip / make an itinerary / 做个行程 / 旅行计划 / 帮我规划旅行.
  Confirm a brief, run three bounded researchers, synthesize and audit a real
  itinerary, then deliver an offline HTML report. Requires pi-herdr-agents in herdr.
---

# Trip Plan

Announce: 我会先确认已有需求，再并行查资料、排行程、检查可行性，最后生成离线 HTML 报告。

## Paths, ownership, and preflight

Resolve `SKILL_DIR` to the **absolute directory containing this loaded SKILL.md**,
not the working project. Read [references/contracts.md](references/contracts.md)
completely. All `scripts/...` below are relative to SKILL_DIR; resolve them before
calling a tool. Select one absolute `RUN_DIR` (`.pi/plans/YYYY-MM-DD-<slug>/` under
the user's project). Pass both absolute directories and the absolute contract
path in **every** child task. Do not rely on child cwd or inherited context.

Parent owns preflight → brief → evidence status index → three researchers →
synthesis → audit/repair → parent photo acquisition/review → design → generation → verification/delivery. Roles are
leaves. Only the three researchers run in parallel. Do not launch a downstream
phase until its actual input files have been read and checked by the parent.

Before research:
- Check the five role definitions and local Python 3 availability (`python` or
  `python3`); use the working interpreter as `PYTHON` in the commands below.
- Model is **exactly `openai-codex/gpt-6-astra`**, in role frontmatter and every
  spawn. Research thinking `low`, synthesis `high`, critic/designer/generator
  `medium`. A registry listing proves role/model registration, **not provider
  authentication or access**. Check authenticated runtime configuration; actual
  access is still confirmed only by a successful request. On authentication
  failure report it and stop spawning; never invent another model ID or silently
  retry on another provider.
- Check available read-only source tools (e.g. network requests via bash with
  timeouts, search if actually installed). A collector is optional, never a
  guessed project-relative dependency. No installer, paid API or fake collector.
  Normal mode is direct-source research plus **image-first best effort**. The
  bundled stdlib `scripts/acquire_images.py` uses the public Commons API and
  original/thumbnail hosts, without credentials/dependencies; verify its absolute path and
  `--help`. Record actual capability restrictions, not “no external helper”.
  No-photo mode requires explicit user preference or documented source attempts /
  unavailable capability. Missing photos never blocks itinerary feasibility.
- If no source access exists at all, explain the limitation and ask once whether
  to proceed with supplied material/a clearly limited guide. Do not claim fresh
  research. A single domain failure does not mean all source access failed.

## Brief and confirmation

`/trip-plan` and `/skill:trip-plan` use the existing native questionnaire. Respect
its confirmation, edits and cancellation. Confirmed raw answers are not a brief
schema: convert faithfully to `brief.json`; retain unknowns and the original
request. **Do not re-ask the questionnaire or re-confirm unchanged answers.**
Never restart a cancelled questionnaire or begin research after cancellation.

Without confirmed answers, offer the existing command, or ask missing questions
**one at a time** in chat. Do not pretend to open UI. Cover destination, date
range, party/needs, pace, interests, must-see/avoid, budget and constraints; then
confirm once. Ask only material follow-ups to existing answers:
- Arrival **local date AND time**, with location. Resolve “凌晨/午夜” to a calendar
  date (e.g. 00:30 on Oct 2, not the evening of Oct 2). Do not infer this from the
  first sightseeing day.
- Departure local date/time/location: distinguish **take-off/departure** from
  landing at home. Ask which it is when it changes the final day; never treat a
  landing time as airport departure time.
- Booked hotel area/address only if door-to-door transfers depend on it. An
  earlier-night booking matters for midnight arrival/check-in, not every trip.
  Do not infer early check-in or a room before the booked night.
- For a **hard budget cap**, clarify all-in vs remaining/local spend and whether
  already-booked transport/hotel spending counts. A soft budget tier needs no
  interrogation about exact sunk costs.

Offer `scope: regional_guide` when the user does not know/want flight/hotel details.
This limits hotel/airport door-to-door timing, **not every outing**. Record accepted
scope, not an endless list of questions. Known dates remain required for a dated
itinerary; offer a separately agreed date window if needed, never invent it.
Unknown noncritical detail may remain null. `relaxed` means slack and choice, not
hotel-only. Only an explicit staycation request sets `staycation: true`.

## Evidence status index and research

Before fan-out write `evidence.json` per the contract even when there is no
collector: capabilities, actual pinned records (possibly empty), source attempts,
errors and limitations. Empty pinned data means **not yet collected**, not “no
places exist”. Never fabricate successful evidence. Keep failure URL, time,
error and affected coverage; direct fallback does not erase failures.

Three concurrent calls use this template (instantiate each row):

| name | agent | category | output | thinking |
| --- | --- | --- | --- | --- |
| `<slug>-research-1` | researcher | poi | research/poi.json | low |
| `<slug>-research-2` | researcher | weather | research/weather.json | low |
| `<slug>-research-3` | researcher | food | research/food.json | low |

```typescript
subagent({
  name: "<slug>-research-1",
  agent: "researcher", model: "openai-codex/gpt-6-astra", thinking: "low",
  task: "SKILL_DIR: <absolute>; RUN_DIR: <absolute>; contract: <absolute>. " +
    "Read contract, brief.json and evidence.json. Class: poi. " +
    "Use relevant pinned evidence if available; otherwise authorized free " +
    "read-only direct sources. Write <absolute RUN_DIR>/research/poi.json. " +
    "Keep failures and uncertainty; bounded summary under 4000 characters."
});
```

Launch all three, then **end the turn**. Resume from automatic completion
messages, accumulate all three results, then read their files. **No polling**:
no status lists, sleeps, tails, wait loops or child spawning by leaves.

Equivalent free read-only source fallback is already authorized. Researchers
may try a relevant official source, public API, tourism site, OSM/Wikimedia etc.
Use timeouts, obey rate limits and access controls, and bound to two attempts per
endpoint. No asking again just to change a free source. No hidden model reruns.
One failed domain leaves partial coverage, not a blocked pipeline. Escalate only
material itinerary choices, new spending/privacy exposure, or genuinely unresolved
feasibility (e.g. a must-see needs a reservation that cannot be verified). Prefer
an honest conditional option over claiming availability. Parent consolidates
source status in evidence.json without overwriting the original failures.

POI researcher records identity-matched Commons `image_candidates`, not bytes,
for primary candidates and useful conditional alternatives. Exact file identity
must be supported by place/file-page evidence; never use a keyword first result,
generic-city image, generated photo or placeholder as a place preview. Parent
selects/downloads only after itinerary selection. No additional parallel roles.
Food researcher normally aims for **3–5 source-backed named venue choices** in
planned areas, even with no special diet. That answer does not mean no food
interest. Maps aid discovery but are not enough alone for local-specialty claims:
try bounded venue/menu, official tourism or reliable public local dining pages
(at most 6 distinct non-map pages, two attempts per endpoint). Do not fill a quota
with anonymous names, generic meals or chains; chains are explicitly labelled
fallbacks. Preserve a smaller valid set with coverage gaps when sources are scant.

## Synthesis

Spawn `<slug>-plan`, role `itinerary-synthesizer`, exact model above, thinking
`high`. Task includes both absolute directories and contract; read brief,
evidence, all three research files and any `evidence.json.research_files`
allowlisted supplements. Write `RUN_DIR/itinerary.json` and
`RUN_DIR/itinerary.md`. Return paths, day summaries, **outing** count, goal
coverage, limitations and unresolved decisions.

Require actual sourced route candidates meeting the interests and must-see list.
A relaxed plan can have short daily optional outings plus rest, not just one
outing for the entire trip. Avoiding crowds is not a ban on unknown-crowd places;
never demand proof of zero crowds, guarantee quiet, or invent hidden places.
Explain sensible timing/alternatives without claiming measured crowd levels.
Interest coverage is separate from outing count: a sourced named meal can meet a
dining interest, as can a relevant sourced optional dining choice, but generic
meals/hotel blocks cannot satisfy must-see goals. New plans actively include
`dining_options` (normally 3–5, grouped by planned areas) or an honest
`dining_coverage_reason`; a smaller set also explains its gap. These are optional
venue choices, not extra outings or forced daily reservations. Connect each to
existing stop IDs and suitable proposed meal/stop opportunities; one choice may
serve several days. Source names/area/address/cuisine/specialties/budget, leave
unknown budgets null, distinguish recommendation rationale from factual quality.
Must-see coverage still needs an outing. Critic checks semantic relevance without
keyword rules; the non-staycation trip-level outing guard remains in force.

Planned starts/durations are **proposals**, permissible with explicit labels.
Verified opening times, prices and transit minutes require fact-level sources;
unknowns are null. Source-backed area centres are valid overview markers, not
exact entrances. Waterbody centres are never walking destinations/navigation
points. Missing coordinates restrict mapping, not the existence of a sourced
area candidate. Unknown flight/hotel data restricts boundary transfers, not the
whole day's regional exploration. Do not attach “待确认” to every rest/meal slot.

## Audit before render; maximum two repair rounds

Parent first runs and reads:

```bash
"$PYTHON" "$SKILL_DIR/scripts/validate_itinerary.py" "$RUN_DIR/itinerary.json" --brief "$RUN_DIR/brief.json" --evidence-dir "$RUN_DIR"
```

This dependency-free check reports **structural_errors**, **goal_errors** and
**unverified** separately. Exit 1 means structural/goal failure, 2 means invalid
input, 0 only means those machine checks passed. It never certifies real-world
feasibility. Do not convert unknown opening/transit fields into invented facts to
make a check green.

Spawn `<slug>-review`, role `itinerary-critic`, thinking `medium`, same model and
absolute paths. Read itinerary JSON/MD, brief, source files, validator output;
write `critique.md`. P0 hard violations/impossibility must be fixed. P1 serious
quality/goal failures must be fixed or explicitly accepted by the user. Missing
noncritical data is a limitation, not automatic P0. No full PASS if feasibility
remains unverified. Parent handles material decisions as they arise, not a final
wall of questions.

For each repair, at most **2 rounds**:
1. Parent copies current `itinerary.json`, `itinerary.md`, `critique.md` into
   `RUN_DIR/repair-N/baseline/` **before** edits. Never overwrite a baseline.
2. Write `repair-N/scope.json`: finding IDs, allowed day/stop IDs, allowed fields,
   additions allowed (default false), and what must remain unchanged. A zero-stop
   goal failure may require new sourced stops: **parent must explicitly authorize
   these additions** and affected days. No blanket “never add” preventing repair.
   If parent obtains necessary supplemental evidence, write the same research
   envelope under `RUN_DIR/research/` (e.g. `repair-1-poi.json`) and add its exact
   run-relative path to `evidence.json.research_files` **before** repair/re-audit.
   Preserve source failures and use unique IDs. Pass these files to synthesizer
   and critic. Validator loads only the required three plus this allowlist:
   no globbing scratch files, missing paths, traversal, symlinks or outside files.
3. Spawn `<slug>-plan` with a targeted repair task, scope and baseline paths;
   same synthesis role/model/thinking. Only authorized changes; write updated
   JSON/MD and `repair-N/changeset.json` mapping each finding to changed IDs,
   fields, before/after values and explanation. Keep unfixed findings visible.
4. Re-run validator, then spawn `<slug>-review` in re-audit mode with baseline,
   scope, changeset and current files. Append closure table and regressions to
   critique.md; compare **all** days for out-of-scope edits, inspect whole touched
   days and JSON/MD consistency. “Fixed” prose is not evidence.
5. Report closed/new findings. A repair opening more problems than it closes
   failed. No rendering until re-audit completes. After two rounds unresolved
   P0/P1 requires user choice/reduced scope; do not silently deliver a feasible
   verdict or continue repairing indefinitely.

## Image-first acquisition, design, generation

After itinerary audit/repair, parent reviews selected primary/optional outing
records' image candidates and source pages for **actual place identity and free
licensing**, then writes `RUN_DIR/images/requests.json` per contract. Include
useful conditional alternatives already represented by optional outing stop IDs;
never add stops just for photos. At most 12 selected photos (one per stop), one
exact confirmed candidate each, ordered by importance. Record attempted sources
and per-stop reasons for missing candidates/capability/explicit opt-out. Prefer
real previews, but never let one missing image remove successful others.

```bash
# SKILL_DIR is the absolute directory of this loaded SKILL.md; PYTHON was checked above.
"$PYTHON" "$SKILL_DIR/scripts/acquire_images.py" --help
"$PYTHON" "$SKILL_DIR/scripts/acquire_images.py" --run-dir "$RUN_DIR"
```

Parent alone runs acquisition sequentially, before design. Helper reads fixed
run-local inputs and writes `images/manifest.json`; no search/first-result guess.
Inspect actual manifest, errors and image identity. Exact-title Commons metadata
must supply recognized free licence, licence page, author/attribution when present,
original and thumbnail URLs. Only exact HTTPS `commons.wikimedia.org` (`/w/api.php`),
`upload.wikimedia.org` (`/wikipedia/commons/`) and `thumb.wikimedia.org`
(`/wikipedia/commons/thumb/`); no ports/userinfo, proxies or redirects. Media URLs
may have only the complete tracking triple `utm_source=commons.wikimedia.org`,
`utm_campaign=imageinfo`, `utm_content=original` (original paths) or `thumbnail`
(thumb paths). Strip that triple before fetching; reject other/duplicate/partial
or encoded query parameters, not arbitrary security tokens. Preserve API URLs in
`original_url`/`thumbnail_url` and actual sanitized URL in `fetch_url`/attempts.
Missing/null/empty `thumbmime` falls back to the validated original raster MIME;
MIME+magic checks remain mandatory. Bounded time/count/bytes, no SVG; atomic writes
and symlink/junction/path checks. No network installs or paid sources.
If source access is unavailable or the user declines photos, parent writes the
honest empty manifest with scoped reasons; otherwise actually try the bundled
helper for confirmed candidates. If none were found, preserve research attempts
and per-place missing reasons instead of pretending a download happened.

Parent appends photo review to critique.md after acquisition: candidate identity,
licensing/attribution, actual files and scoped failures. Critic's pre-acquisition
review checks candidate semantics; no extra parallel role or mandatory second
critic spawn. Metadata checks cannot prove a photograph depicts the place.
Missing photos are a presentation limitation, not P0 or a feasibility blocker.

Spawn `<slug>-ui`, role `itinerary-designer`, exact model, thinking `medium`.
Read brief, itinerary JSON/MD and manifest; write `design.md`, `shell.html`.
Then spawn `<slug>-build`, role `itinerary-generator`, same model, thinking
`medium`; read these plus critique/contract and write **exactly
`<absolute RUN_DIR>/trip.html`**. No extra nested output directory. Include exact
helper paths in each task. Fixed section order:
`#top → #itinerary → #decisions (only if open choices, collapsed) → #prep → #credits`.
No preamble/audit wall between the closed title block and first marked day;
only neutral open layout wrappers may intervene. Render optional restaurant
choice cards with `data-dining-id` near related days or in a dedicated subsection
**inside #itinerary, after day one begins**, once per option, grouped by area.
Repeat-use day links are fine; no mandatory bookings or new questionnaire.
Prep may use plain labelled
checkboxes without form/name/events; other inputs/forms/buttons are forbidden.
Actual limitations appear
briefly near affected stops or in prep; decisions are real unresolved choices,
not settled preferences rewritten as questions. All-source provenance stays in
artifacts/credits, not codes and API chatter in the human itinerary.

Use system CJK fonts, mobile/print CSS, inline static SVG overview if useful.
No map tiles, scripts, external assets or fake route lines between area markers.
Show all successful photos at their matching stop cards, including optional
alternatives, with real alt text and author/licence/page credits. No blank photo
boxes, placeholders or generated substitutes; omit only affected missing places.
No placeholder `<img>` even in shell. With zero images **skip embedding**. With
images generator only copies manifest src; parent (not a model) runs:

```bash
"$PYTHON" "$SKILL_DIR/scripts/embed_images.py" "$RUN_DIR/trip.html" --manifest "$RUN_DIR/images/manifest.json"
```

It only embeds manifest-authorized PNG/JPEG/GIF/WebP files under RUN_DIR/images;
no network, arbitrary files, SVG uploads or path escape. It writes in place only
after checking every image. Credits remain required.

## Parent verification and delivery

Read the actual `RUN_DIR/trip.html` (do not trust a child success message), plus
validator and critique. Run:

```bash
"$PYTHON" "$SKILL_DIR/scripts/verify_report.py" "$RUN_DIR/trip.html" --itinerary "$RUN_DIR/itinerary.json" --manifest "$RUN_DIR/images/manifest.json"
```

Verify selected dining names/cards, source/stop references and meaningful choice
coverage (not generic meal slots). Verify photos match the actual named attraction,
all successful selected photos render, licences/attributions are retained, and
missing reasons are scoped. Do not claim semantic identity from MIME checks.
Verify confirmed brief, three research files, honest source errors, real outings,
goal coverage, audit-before-render and repair re-audit evidence. Verify no-photo
mode has **no img**, final images inline and attributed, optional decisions
collapsed/after itinerary, no invented prices/hours/transit, no source jargon in
decisions, settled choices stay settled. Helper checks cannot prove semantic
truth, coordinate identity, mobile appearance or physical feasibility: parent
must read content and disclose what was not verified. Generator summary must
include exact output path, bytes, day/outing counts, image count, unresolved
choices/limitations, and actual validator/render-check results (pre-embed may be
marked pending; parent must run final check).

Deliver the existing exact HTML path, short daily shape and meaningful remaining
limitations/decisions; never call it fully feasible when timings remain unknown.
Visa/entry/safety guidance is not generated; refer users to official channels.

## Maintenance tests (not trip execution)

```bash
PYTHONIOENCODING=utf-8 "$PYTHON" -B -m unittest discover -s "$SKILL_DIR/tests" -p 'test_*.py' -v
PYTHONIOENCODING=utf-8 node --experimental-strip-types "$SKILL_DIR/tests/questionnaire.mjs"
```
