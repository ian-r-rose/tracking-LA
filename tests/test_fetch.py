"""One source's failure, of whatever kind, doesn't stop the others."""

import json
from datetime import date

import httpx
import pytest

from tracking_la import cli
from tracking_la.sources import Source

DAY = date.today()


def meeting(body):
    return {"body": body, "date": DAY, "agenda_url": f"https://example.org/{body}"}


def item(m):
    return {"id": f"{m['body']}-1", "body": m["body"], "meeting_date": DAY.isoformat(), "item_number": "1",
            "title": "t", "text": "t", "urls": [m["agenda_url"]]}


def crash(*args):
    b"\xd4".decode()  # what Airtable's MessagePack did to the Cultural Affairs listing


GOOD = Source("good", lambda s, e, c: [meeting("good")], lambda m, content: [item(m)])


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    def run(*sources, command=lambda: cli.fetch(30)):
        saved = []
        monkeypatch.setattr(cli, "SOURCES", list(sources))
        monkeypatch.setattr(cli, "DATA", tmp_path)
        monkeypatch.setattr(cli, "AGENDAS", tmp_path / "agendas.json")
        monkeypatch.setattr(cli, "PROCESSED", tmp_path / "outcome-sources.json")
        monkeypatch.setattr(cli, "upsert_item", lambda i: saved.append(i["id"]) or "new")
        monkeypatch.setattr(cli, "http_client", lambda **kw: httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"agenda"))))
        with pytest.raises(SystemExit):  # still a failure, so it's seen
            command()
        return saved, capsys.readouterr().out

    return run


def test_a_listing_that_crashes(run, tmp_path):
    saved, out = run(Source("bad", crash, crash), GOOD)
    assert saved == ["good-1"]
    assert "failed: bad: UnicodeDecodeError" in out
    assert json.loads((tmp_path / "agendas.json").read_text()) == {"https://example.org/good": DAY.isoformat()}


def test_an_agenda_that_crashes_is_tried_again(run, tmp_path):
    saved, out = run(Source("bad", lambda s, e, c: [meeting("bad")], crash), GOOD)
    assert saved == ["good-1"]
    assert "failed: https://example.org/bad: UnicodeDecodeError" in out
    assert "https://example.org/bad" not in json.loads((tmp_path / "agendas.json").read_text())


def test_outcomes_that_crash(run):
    read = []
    bad = Source("bad", crash, crash, outcome_url=lambda m: "https://example.org/m", meeting_outcomes=crash)
    good = Source("good", lambda s, e, c: [meeting("good")], crash, outcome_url=lambda m: "https://example.org/m",
                  meeting_outcomes=lambda m, content: read.append(m["body"]) or {})
    _, out = run(bad, good, command=lambda: cli.outcomes(30))
    assert read == ["good"] and "failed: bad: UnicodeDecodeError" in out
