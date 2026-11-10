"""The LMS's firewall answers some automated requests with a challenge: 202, an empty
body and an x-amzn-waf-action header."""

import json
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
import pytest

from tracking_la import cli, reportbacks
from tracking_la.sources import council

PAGE = (Path(__file__).parent / "fixtures" / "council" / "cf-26-0251.html").read_text()
URL = council.council_file_url("26-0251")


def challenge():
    return httpx.Response(202, headers={"x-amzn-waf-action": "challenge"})


def client(respond):
    return httpx.Client(transport=httpx.MockTransport(respond))


def test_a_page_is_requested_once_per_run():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=PAGE)

    pages = council.FilePages(client(respond))
    assert pages.get(URL) == pages.get(URL) == PAGE
    assert len(requests) == 1


def test_nothing_more_is_requested_after_a_challenge():
    requests = []

    def respond(request):
        requests.append(request)
        return challenge()

    pages = council.FilePages(client(respond))
    for number in ("26-0251", "26-0252", "26-0253"):
        with pytest.raises(council.Challenged):
            pages.get(council.council_file_url(number))
    assert len(requests) == 1
    failed = []
    pages.report(failed)
    assert len(failed) == 1 and "3 Council File page(s)" in failed[0]


def test_a_challenged_outcome_is_reported_not_skipped(tmp_path, monkeypatch):
    # An empty body once skipped these without a word: four fetches recorded no Council outcome.
    path = tmp_path / "items" / "council-plum" / "2026" / "item.json"
    path.parent.mkdir(parents=True)
    item = {"id": "item", "body": "council-plum", "meeting_date": date.today().isoformat(), "text": "", "urls": ["agenda", URL]}
    path.write_text(json.dumps(item))
    monkeypatch.setattr(cli, "DATA", tmp_path)
    with client(lambda request: challenge()) as http:
        failed, lms = [], council.FilePages(http)
        cli.followed_outcomes(http, Counter(), failed, lms)
        lms.report(failed)
    assert len(failed) == 1 and "firewall" in failed[0]
    assert json.loads(path.read_text()) == item


def test_a_challenge_leaves_report_backs_alone(tmp_path):
    path = tmp_path / "report-backs" / "26-0251.json"
    path.parent.mkdir()
    record = {"council_file": "26-0251", "title": "Gaffey Street", "motion_url": "m", "adopted": "2026-03-25", "documents": []}
    path.write_text(json.dumps(record))
    folder = tmp_path / "items" / "council-transportation" / "2026"
    folder.mkdir(parents=True)
    (folder / "item.json").write_text(json.dumps({"text": "[Council File 26-0251]", "urls": ["agenda", URL]}))
    failed = []
    reportbacks.update(client(lambda request: challenge()), Counter(), failed, date(2026, 11, 2), tmp_path)
    assert json.loads(path.read_text()) == record
    assert len(failed) == 1 and "firewall" in failed[0]


def test_the_fetch_workflows_outcomes_leave_the_lms_alone(tmp_path, monkeypatch):
    # Council File pages are read by `council-files`, where the firewall doesn't challenge.
    path = tmp_path / "items" / "council-plum" / "2026" / "item.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"id": "item", "body": "council-plum", "meeting_date": date.today().isoformat(), "text": "", "urls": ["agenda", URL]}))
    monkeypatch.setattr(cli, "DATA", tmp_path)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=PAGE)

    with client(respond) as http:
        cli.followed_outcomes(http, Counter(), [])
        assert not requests
        cli.followed_outcomes(http, Counter(), [], council.FilePages(http))
        assert [str(r.url) for r in requests] == [URL]
