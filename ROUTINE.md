# Routine

Instructions for the scheduled Claude Code routine that keeps `data/` up to date.

## 1. Fetched data

The **Fetch** GitHub workflow (`.github/workflows/fetch.yml`) fetches agendas and records outcomes from journals and minutes, then commits them as `Fetch YYYY-MM-DD`. It runs daily in the early morning (09:00 UTC), hours before this routine. It runs there because this routine's sandbox can't reach some City sites. Don't run `tracking-la fetch` or `tracking-la outcomes` here.

Check the Fetch commits since the last `Digest` commit (`git log --format='%h %s%n%b' <last digest commit>..HEAD`). If any lists failed sources, name them in the digest's intro (a source that failed once and then succeeded doesn't need a mention). If there's no Fetch commit from today, the workflow either failed or found nothing new; mention it in your final summary. An `empty:` line means an agenda produced no items, which can be a changed agenda format; mention those in your final summary too, not in the digest.

## 2. Extract (Haiku subagents)

Find item files under `data/items/` that have no `summary` field. Split them into batches of about 15 and give each batch to a subagent running `haiku`, with the instructions below.

> For each item JSON file listed, read the `text` field and add these fields to the file. Leave every existing field unchanged and keep the file valid JSON (2-space indent).
>
> - `summary`: one or two plain sentences on what is being decided, for a resident skimming a digest. Name the place and the action, e.g. "Zone change to allow eight small-lot homes replacing a single-family house at 9247 N Wakefield Ave in North Hills." No case numbers or code citations.
> - `topics`: one or more of `parks`, `transportation`, `land_use`, `housing`, `environment`, `budget`, `public_safety`, `other`. Use `land_use` for zoning, entitlements, permits and historic designations. Add `housing` when the item creates or removes housing units. Add `parks` whenever a *public* park, plaza, trail or other public open space is involved, even if the item is mainly about zoning or historic status. A project's own private open space (courtyards, roof decks, "open space" required by code) doesn't count. Add `transportation` only when the item changes public streets, sidewalks, bike lanes or transit (e.g. street vacations, new private streets, transit facilities), or when transportation is central to the item. A project's own parking or bicycle-parking counts, including parking reductions, don't count.
> - `locations`: a list of `{"text": ...}` objects, one per distinct site in the item: street addresses (one entry per site, choosing a single representative address for a range such as "4127 – 4129 E Supreme Ct"), intersections, or named places like parks. Write addresses as they would be geocoded: "16300 Foothill Blvd, Los Angeles, CA". For a street segment ("Avalon Blvd from Martin Luther King Jr Blvd to 56th St"), give one intersection at each end ("Avalon Blvd & 56th St, Los Angeles, CA"). For a park or other named facility, give its name as written ("Sycamore Grove Park"). Leave the list empty for citywide items or items that list only council districts.
> - `details`: an object with whatever of these the item states: `case_numbers` (list), `council_district` (integer), `plan_area` (string), `applicant` (string), `action` (short phrase, e.g. "appeal of Zoning Administrator approval", "contract award"), `amount` (dollar figure as written, e.g. "$6,844,197"), `bureau` (Public Works bureau, if named), `council_file` (Council File number, e.g. "25-0843"). Leave out anything not stated.
>
> Don't make up information. Use only what the item text says.
>
> Don't run any git commands, and don't edit any file other than the item files listed.

Then run `uv run tracking-la check`. It must pass before you continue. Agents sometimes report success after writing malformed files, so fix any file it flags (by hand, or by sending it back to a subagent).

## 3. Locate

```
uv run tracking-la locate
```

Geocodes new locations with the City's locator (cached in `geo/geocode-cache.json`), sets each location's `neighborhood`, and lists items in or near the neighborhoods in `config/interests.yaml`.

## 4. Digest (main model)

```
uv run tracking-la score
```

This lists every item not yet covered by a digest, one line each (score, meeting date, file, reasons for the score, summary), highest score first. Read every line: all of them are marked as covered when this digest is committed, so an item you skip here won't come back. Open the JSON files of items that might matter, and for anything that might matter, the staff reports linked in `urls`. Some sites (ens.lacity.org) can't be reached from this sandbox; work from the item text when a link fails. Metro items link many large attachments (presentations, funding tables, environmental documents): decide from the item text, and open one attachment only when you're including an item whose text doesn't say where the project is. Then decide what is worth Ian's attention. Use the score as a guide, not a cutoff: a high score can be routine (a single-family hillside home), and a low score can matter (a citywide parks policy).

**Re-running on the same day** rewrites that day's digest: `score` and `decisions` default to today's date and also list what today's digest already covered. If `data/digests/<today>.md` exists, write it again from scratch, and remove the `flag` field from items you no longer include. Publishing updates the existing issue rather than opening a new one. (`--date YYYY-MM-DD` does the same for an earlier digest.)

For each item you include, add a `flag` field to its JSON file: `{"reason": "<one sentence on why it matters to Ian>"}`. Base the reason on the item, related items in `data/` and `config/interests.yaml` (e.g. "runs through East Hollywood and Koreatown, two of the watched neighborhoods"), never on guesses about Ian's habits or plans ("a corridor Ian travels"). The same goes for the "why it matters" text in the digest.

If reviewing shows an extraction field is wrong (a misspelled street that won't geocode, a missing `parks` tag that a staff report makes obvious, a misleading summary), correct it in the item file, then rerun `uv run tracking-la locate` if you changed `locations`. Say what you corrected and why in the commit message; git history is the record. Don't change scraper-owned fields (`tracking-la check` rejects that).

Write `data/digests/YYYY-MM-DD.md` (today's date). It has two kinds of entries, grouped together by body (commission, board or other source): agenda items (from `score`) and decisions on earlier items (from `uv run tracking-la decisions`).

```markdown
# Commissions digest — <Month D, YYYY>

Agenda items from meetings <Month D> – <Month D, YYYY>, and decisions recorded from <journals and minutes of ...>. <N> items reviewed; <M> listed below.

## <Body's full name>

<One sentence on what this body decides or publishes.>

- **<Mon D>** · upcoming · <neighborhood> — <summary, rewritten if needed>. <Why it matters.> [Agenda](<url>) · [Staff report](<url>)
- **<Mon D>** · <neighborhood> — <item, in a few words>: **<approved 5–0 / continued to Oct 9 / withdrawn / ...>**. [Journal or minutes](<outcome source>)
```

Which decisions to include: every outcome for an item flagged in an earlier digest (marked `*` by `decisions`). For other items, only withdrawals, denials, continuances and split votes, plus anything you'd have listed as an agenda item. Leave out unanimous approvals of routine items. When an item has both a listed agenda entry and a decision, give one bullet with the outcome in it.

Rules:
- One section per body with anything listed, in this order: City Planning Commission, Area Planning Commissions (alphabetical), Cultural Heritage Commission, City Council committees (Planning and Land Use Management first), then any others. A committee's action is a recommendation to the full Council; when a decision says what Council did next (adopted, "Council action final"), say so. There's no separate decisions section.
- Within a section, every `upcoming` bullet comes before any past one: upcoming items soonest first, then past items and decisions newest first.
- Mark meetings on or after today's date as `upcoming`. Don't describe outcomes of past meetings unless an item or a recorded decision says what was decided.
- Don't refer to earlier or later digests ("first", "this time", "since last time", "as reported earlier"). Each digest should read the same way whenever it's generated. If a decision contradicts how an item was described before (e.g. it was withdrawn), state the outcome plainly.
- Routine items in Ian's neighborhoods (single houses, cell sites) get a short bullet with no "why it matters".
- Say where an item is in plain words ("in Echo Park"). Don't recite the selection rules in the digest ("Echo Park is a watched neighborhood", "A public park is involved"); the reader knows why items are there. Before calling a place inside, outside or next to the watched neighborhoods, in a bullet or a `flag` reason, check the list in `config/interests.yaml`.
- Keep the whole digest skimmable in two minutes.

Then mark everything you reviewed as covered and check the files:

```
uv run tracking-la mark-digested YYYY-MM-DD
uv run tracking-la check
```

## 5. Commit

Commit `data/` and `geo/geocode-cache.json` with the message `Digest YYYY-MM-DD`, adding a line for each correction made during review, then push.

The push triggers `.github/workflows/publish.yml`, which opens a GitHub issue for the new digest (or updates it, if the digest was edited) and redeploys the site.
