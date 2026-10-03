# Routine

Instructions for the scheduled Claude Code routine that keeps `data/` up to date.

## 1. Fetched data

The **Fetch** GitHub workflow (`.github/workflows/fetch.yml`) fetches agendas and records outcomes from journals and minutes, then commits them as `Fetch YYYY-MM-DD`. It runs daily, including an hour before this routine. It runs there because this routine's sandbox can't reach some commission sites. Don't run `lacomm fetch` or `lacomm outcomes` here.

Check the Fetch commits since the last `Digest` commit (`git log --format='%h %s%n%b' <last digest commit>..HEAD`). If any lists failed sources, name them in the digest's intro (a source that failed once and then succeeded doesn't need a mention). If there's no Fetch commit from today, the workflow either failed or found nothing new; mention it in your final summary.

## 2. Extract (Haiku subagents)

Find item files under `data/items/` that have no `summary` field. Split them into batches of about 15 and give each batch to a subagent running `haiku`, with the instructions below.

> For each item JSON file listed, read the `text` field and add these fields to the file. Leave every existing field unchanged and keep the file valid JSON (2-space indent).
>
> - `summary`: one or two plain sentences on what is being decided, for a resident skimming a digest. Name the place and the action, e.g. "Zone change to allow eight small-lot homes replacing a single-family house at 9247 N Wakefield Ave in North Hills." No case numbers or code citations.
> - `topics`: one or more of `parks`, `transportation`, `land_use`, `housing`, `environment`, `budget`, `public_safety`, `other`. Use `land_use` for zoning, entitlements, permits and historic designations. Add `housing` when the item creates or removes housing units. Add `parks` whenever a *public* park, plaza, trail or other public open space is involved, even if the item is mainly about zoning or historic status. A project's own private open space (courtyards, roof decks, "open space" required by code) doesn't count. Add `transportation` only when the item changes public streets, sidewalks, bike lanes or transit (e.g. street vacations, new private streets, transit facilities), or when transportation is central to the item. A project's own parking or bicycle-parking counts, including parking reductions, don't count.
> - `locations`: a list of `{"text": ...}` objects, one per distinct site in the item: street addresses (one entry per site, choosing a single representative address for a range such as "4127 – 4129 E Supreme Ct"), intersections, or named places like parks. Write addresses as they would be geocoded: "16300 Foothill Blvd, Los Angeles, CA". For a street segment ("Avalon Blvd from Martin Luther King Jr Blvd to 56th St"), give one intersection at each end ("Avalon Blvd & 56th St, Los Angeles, CA"). For a park or other named facility, give its name as written ("Sycamore Grove Park"). Leave the list empty for citywide items or items that list only council districts.
> - `details`: an object with whatever of these the item states: `case_numbers` (list), `council_district` (integer), `plan_area` (string), `applicant` (string), `action` (short phrase, e.g. "appeal of Zoning Administrator approval", "contract award"), `amount` (dollar figure as written, e.g. "$6,844,197"), `bureau` (Public Works bureau, if named). Leave out anything not stated.
>
> Don't make up information. Use only what the item text says.
>
> Don't run any git commands, and don't edit any file other than the item files listed.

Then run `uv run lacomm check`. It must pass before you continue. Agents sometimes report success after writing malformed files, so fix any file it flags (by hand, or by sending it back to a subagent).

## 3. Locate

```
uv run lacomm locate
```

Geocodes new locations with the City's locator (cached in `geo/geocode-cache.json`), sets each location's `neighborhood`, and lists items in or near the neighborhoods in `config/interests.yaml`.

## 4. Digest (main model)

```
uv run lacomm score --limit 30
```

This lists items not yet covered by a digest, highest score first, with the reasons for each score. Read the top items' JSON files, and for anything that might matter, the staff reports linked in `urls`. Some sites (ens.lacity.org) can't be reached from this sandbox; work from the item text when a link fails. Metro items link many large attachments (presentations, environmental documents): decide from the item text, and open at most one attachment, and only for an item you're including. Then decide what is worth Ian's attention. Use the score as a guide, not a cutoff: a high score can be routine (a single-family hillside home), and a low score can matter (a citywide parks policy).

For each item you include, add a `flag` field to its JSON file: `{"reason": "<one sentence on why it matters to Ian>"}`.

If reviewing shows an extraction field is wrong (a misspelled street that won't geocode, a missing `parks` tag that a staff report makes obvious, a misleading summary), correct it in the item file, then rerun `uv run lacomm locate` if you changed `locations`. Say what you corrected and why in the commit message; git history is the record. Don't change scraper-owned fields (`lacomm check` rejects that).

Write `data/digests/YYYY-MM-DD.md` (today's date):

```markdown
# Commissions digest — <Month D, YYYY>

Agenda items from meetings <Month D> – <Month D, YYYY>. <N> items reviewed; <M> listed below.

## <Commission full name>

<One sentence on what this commission decides.>

- **<Mon D>** · upcoming · <neighborhood> — <summary, rewritten if needed>. <Why it matters.> [Agenda](<url>) · [Staff report](<url>)
- **<Mon D>** · <neighborhood> — ...
```

Then, if `uv run lacomm decisions` lists anything, add this section after the intro line:

```markdown
## Decisions recorded

- **<Commission>, <Mon D>** · <neighborhood> — <item, in a few words>: **<approved 5–0 / continued / withdrawn / ...>**. [Journal or minutes](<outcome source>)
```

List every outcome for an item flagged in an earlier digest (marked `*`). For other items, list only withdrawals, denials, continuances and split votes. Leave out unanimous approvals of routine items. If a decision changes what an earlier digest said (e.g. an item it described was withdrawn), say so plainly.

Rules:
- One section per commission that has listed items, in this order: City Planning Commission, Area Planning Commissions (alphabetical), Cultural Heritage Commission, then any others. Within a section, list items by meeting date, oldest first.
- Mark meetings on or after today's date as `upcoming`. Don't describe outcomes of past meetings unless an item says what was decided.
- Don't refer to earlier or later digests ("first", "this time", "since last time"). Each digest should read the same way whenever it's generated.
- Routine items in Ian's neighborhoods (single houses, cell sites) get a short bullet with no "why it matters".
- Keep the whole digest skimmable in two minutes.

Then mark everything you reviewed as covered and check the files:

```
uv run lacomm mark-digested YYYY-MM-DD
uv run lacomm check
```

## 5. Commit

Commit `data/` and `geo/geocode-cache.json` with the message `Digest YYYY-MM-DD`, adding a line for each correction made during review, then push.

The push triggers `.github/workflows/publish.yml`, which opens a GitHub issue for the new digest (or updates it, if the digest was edited) and redeploys the site.
