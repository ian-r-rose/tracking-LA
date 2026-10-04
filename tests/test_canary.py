from datetime import date

import httpx

from tracking_la import canary
from tracking_la.sources import Source

TODAY = date(2026, 10, 3)


class Client:
    def get(self, url):
        return httpx.Response(200, content=b"agenda", request=httpx.Request("GET", url))


def source(meetings, items):
    return Source("test", lambda start, end, client: meetings, lambda meeting, content: items)


def meeting(day):
    return {"date": date(2026, 9, day), "agenda_url": f"https://example.org/{day}"}


def test_healthy_source():
    assert canary.check_source(source([meeting(1), meeting(15)], [{"id": "x"}]), Client(), TODAY) is None


def test_no_meetings_listed():
    assert "no meetings listed" in canary.check_source(source([], []), Client(), TODAY)


def test_agendas_that_parse_to_nothing():
    problem = canary.check_source(source([meeting(d) for d in (1, 8, 15, 22)], []), Client(), TODAY)
    assert problem.startswith("the newest 3 agenda(s) produced no items")
    assert "/22" in problem and "/1" not in problem.replace("/15", "")
