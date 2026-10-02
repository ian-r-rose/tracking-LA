"""Build the static site: every digest, newest first, plus the commissions guide.

Plain HTML with relative links, so it works on GitHub Pages under /<repo>/ and
when opened from disk.
"""

import html
import re
import shutil
from pathlib import Path

import markdown

from lacomm.store import DATA

ROOT = DATA.parent
TITLE = "LA Commissions Watch"

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
<a href="{prefix}commissions.html">Commissions</a>
</header>
<main>
{body}
</main>
<footer>Agendas, minutes and journals from LA City commission websites, summarized with Claude.
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

    guide = (ROOT / "docs" / "commissions.md").read_text()
    (out / "commissions.html").write_text(page(f"Commissions · {TITLE}", render(guide)))
    return len(digests)
