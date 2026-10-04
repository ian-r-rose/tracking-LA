"""Build the static site: every digest, newest first, the guide to sources (docs/commissions.md), and the
table of pending report backs.

Plain HTML with relative links, so it works on GitHub Pages under /<repo>/ and
when opened from disk.
"""

import html
import re
import shutil
from datetime import date
from pathlib import Path

import markdown

from tracking_la import reportbacks
from tracking_la.store import DATA

ROOT = DATA.parent
TITLE = "Tracking LA"

STYLE = """
:root { --bg: #fdfcfa; --fg: #1f1d1a; --muted: #6b665e; --line: #e4e0d8; --link: #1d5c8f; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #1a1917; --fg: #e8e5df; --muted: #9c978e; --line: #34312c; --link: #7fb5e0; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
header, main, footer { max-width: 46rem; margin: 0 auto; padding: 0 16px; }
header { display: flex; flex-wrap: wrap; gap: .25rem 1.25rem; align-items: baseline;
  padding-top: 1.25rem; padding-bottom: .75rem; border-bottom: 1px solid var(--line); }
header .name { font-weight: 700; color: var(--fg); text-decoration: none; margin-right: auto; }
a { color: var(--link); }
h1 { font-size: 1.6rem; line-height: 1.25; margin: 1.5rem 0 .75rem; }
h2 { font-size: 1.25rem; margin: 2rem 0 .5rem; padding-top: .5rem; border-top: 1px solid var(--line); }
h3 { font-size: 1.05rem; margin: 1.25rem 0 .25rem; }
li { margin: .4rem 0; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; display: block; overflow-x: auto; }
th, td { text-align: left; vertical-align: top; padding: .35rem .5rem; border-bottom: 1px solid var(--line); }
.status { white-space: nowrap; font-variant-numeric: tabular-nums; }
.archive { list-style: none; padding: 0; }
.archive li { display: flex; gap: 1rem; }
.archive .date { color: var(--muted); font-variant-numeric: tabular-nums; min-width: 6.5rem; }
footer { color: var(--muted); font-size: .85rem; padding-top: 2rem; padding-bottom: 2rem; }
"""


def page(title: str, body: str, prefix: str = "") -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{prefix}style.css">
</head>
<body>
<header>
<a class="name" href="{prefix}index.html">{TITLE}</a>
<a href="{prefix}archive.html">Archive</a>
<a href="{prefix}commissions.html">Sources</a>
<a href="{prefix}report-backs.html">Report backs</a>
</header>
<main>
{body}
</main>
<footer>Agendas, minutes and journals from LA City and Metro websites, summarized with Claude.
Summaries can be wrong; follow the links to the source documents.</footer>
</body>
</html>
"""


def render(text: str) -> str:
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)  # front matter
    return markdown.markdown(text, extensions=["tables"])


def heading(text: str) -> str:
    match = re.search(r"^# (.+)$", text, re.M)
    return match.group(1).strip() if match else ""


def build(out: Path) -> int:
    if out.exists():
        shutil.rmtree(out)
    (out / "digests").mkdir(parents=True)
    (out / "style.css").write_text(STYLE.lstrip())

    digests = sorted((DATA / "digests").glob("*.md"), reverse=True)
    rows = []
    for path in digests:
        text = path.read_text()
        title = heading(text) or path.stem
        (out / "digests" / f"{path.stem}.html").write_text(page(title, render(text), "../"))
        rows.append(f'<li><span class="date">{path.stem}</span><a href="digests/{path.stem}.html">{html.escape(title)}</a></li>')

    archive = '<h1>All digests</h1>\n<ul class="archive">\n' + "\n".join(rows) + "\n</ul>"
    (out / "archive.html").write_text(page(f"Archive · {TITLE}", archive))

    if digests:
        latest = digests[0].read_text()
        index = render(latest) + '\n<p><a href="archive.html">Earlier digests</a></p>'
    else:
        index = "<h1>No digests yet</h1>"
    (out / "index.html").write_text(page(TITLE, index))

    (out / "report-backs.html").write_text(page(f"Report backs · {TITLE}", report_backs_page()))

    guide = (ROOT / "docs" / "commissions.md").read_text()
    (out / "commissions.html").write_text(page(f"Sources · {TITLE}", render(guide)))
    return len(digests)


def report_backs_page(today: date | None = None) -> str:
    today = today or date.today()
    rows = []
    for record, request, doc, confirmed in reportbacks.table(today):
        due = reportbacks.due(record, request)
        if doc:
            late = (date.fromisoformat(doc["date"]) - due).days if due else None
            status = f"filed {doc['date']}" + (f", {late} days late" if late and late > 0 else "")
            status += "" if confirmed else " (not yet checked)"
        else:
            late = (today - due).days if due else None
            status = f"pending, {late} days overdue" if late and late > 0 else "pending"
        link = reportbacks.council.council_file_url(record["council_file"])
        rows.append(
            "<tr>"
            f'<td><a href="{html.escape(link)}">{html.escape(record["council_file"])}</a></td>'
            f"<td>{html.escape(', '.join(request['departments']))}</td>"
            f"<td>{html.escape(request['asks'])}"
            + (f' · <a href="{html.escape(doc["url"])}">report</a>' if doc and doc["url"] else "")
            + "</td>"
            f"<td>{record['adopted']}</td>"
            f"<td>{due or 'none'}</td>"
            f'<td class="status">{html.escape(status)}</td>'
            "</tr>"
        )
    intro = (
        "<h1>Report backs</h1>\n<p>Departments that City Council has asked to look into something and "
        "report back, on Council Files from the watched committees: pending ones first, then those filed "
        "in the last year. Due dates count from Council's adoption of the motion. Committees sometimes "
        "change a deadline, which this doesn't see; check the Council File.</p>"
    )
    if not rows:
        return intro + "\n<p>None right now.</p>"
    head = "<tr><th>Council File</th><th>Asked of</th><th>Asked for</th><th>Adopted</th><th>Due</th><th>Status</th></tr>"
    return intro + f"\n<table>\n{head}\n" + "\n".join(rows) + "\n</table>"
