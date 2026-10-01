# Routine

Instructions for the scheduled Claude Code routine that keeps `data/` up to date.

## 1. Fetch

```
uv run lacomm fetch --since 30
```

## 2. Extract (Haiku subagents)

Find item files under `data/items/` that have no `summary` field. Split them into batches of about 15 and give each batch to a subagent running `haiku`, with the instructions below.

> For each item JSON file listed, read the `text` field and add these fields to the file. Leave every existing field unchanged and keep the file valid JSON (2-space indent).
>
> - `summary`: one or two plain sentences on what is being decided, for a resident skimming a digest. Name the place and the action, e.g. "Zone change to allow eight small-lot homes replacing a single-family house at 9247 N Wakefield Ave in North Hills." No case numbers or code citations.
> - `topics`: one or more of `parks`, `transportation`, `land_use`, `housing`, `environment`, `budget`, `public_safety`, `other`. Use `land_use` for zoning, entitlements, permits and historic designations. Add `housing` when the item creates or removes housing units. Add `parks` whenever a park, plaza, trail or other public open space is involved, even if the item is mainly about zoning or historic status. Add `transportation` for streets, sidewalks, bike lanes, transit, parking requirements and driveways onto public streets.
> - `locations`: a list of `{"text": ...}` objects, one per distinct site in the item: street addresses (one entry per site, choosing a single representative address for a range such as "4127 – 4129 E Supreme Ct"), intersections, or named places like parks. Write addresses as they would be geocoded: "16300 Foothill Blvd, Los Angeles, CA". Leave the list empty for citywide items.
> - `details`: an object with whatever of these the item states: `case_numbers` (list), `council_district` (integer), `plan_area` (string), `applicant` (string), `action` (short phrase, e.g. "appeal of Zoning Administrator approval"). Leave out anything not stated.
>
> Don't make up information. Use only what the item text says.

Then run `uv run lacomm check`. It must pass before you continue. Agents sometimes report success after writing malformed files, so fix any file it flags (by hand, or by sending it back to a subagent).
