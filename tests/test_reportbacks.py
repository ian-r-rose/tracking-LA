import json
from datetime import date
from pathlib import Path

from tracking_la import reportbacks

FIXTURES = Path(__file__).parent / "fixtures" / "council"
DOT = "https://cityclerk.lacity.org/onlinedocs/2026/26-0251_rpt_dot_07-31-26.pdf"


def test_page_gives_motion_adoption_and_documents_since():
    page = reportbacks.parse_page((FIXTURES / "cf-26-0251.html").read_text())
    assert page["title"].startswith("Interstate 110 / Gaffey Street")
    assert page["introduced"] == "2026-02-20" and page["adopted"] == "2026-03-25"
    assert page["motion_url"].endswith("26-0251_misc_02-20-26.pdf")
    # Council Action, Amending Motion, the committee's report and speaker cards aren't reports.
    assert page["documents"] == [{"date": "2026-07-31", "title": "Report from Department of Transportation", "url": DOT}]


def test_operative_text_starts_at_the_move_paragraphs():
    text = "Background about the incident.\n\nI THEREFORE MOVE that LADOT report back within 30 days."
    assert reportbacks.operative_text(text) == "I THEREFORE MOVE that LADOT report back within 30 days."


def test_candidates_name_an_asked_department_or_come_from_the_mayor():
    request = {"departments": ["Los Angeles Department of Transportation"], "asks": "x"}
    assert reportbacks.candidate({"title": "Report from Department of Transportation"}, request)
    assert reportbacks.candidate({"title": "Report from Board of Transportation Commissioners"}, request)
    assert reportbacks.candidate({"title": "Report from Mayor"}, request)
    assert not reportbacks.candidate({"title": "Report from City Administrative Officer"}, request)
    assert reportbacks.candidate({"title": "Report from CAO"}, {"departments": ["City Administrative Officer"], "asks": "x"})


def record(**extra):
    return {
        "council_file": "26-0251", "adopted": "2026-03-25",
        "documents": [
            {"date": "2026-05-01", "title": "Report from Mayor", "url": "mayor.pdf", "excerpt": "..."},
            {"date": "2026-07-31", "title": "Report from Department of Transportation", "url": DOT, "excerpt": "..."},
        ],
        "requests": [{"departments": ["LADOT"], "asks": "Incident response", "deadline": 30}],
        **extra,
    }


def test_unchecked_candidates_are_unconfirmed_until_reviewed():
    r = record()
    assert reportbacks.filed(r, 0) == (r["documents"][0], False)
    assert reportbacks.to_review(r) == r["documents"]
    r = record(document_reviews={"mayor.pdf": [], DOT: [0]})  # the Mayor's transmittal was about something else
    assert reportbacks.filed(r, 0) == (r["documents"][1], True)
    assert reportbacks.confirmed(r, 0) == r["documents"][1] and reportbacks.to_review(r) == []
    assert reportbacks.due(r, r["requests"][0]) == date(2026, 4, 24)


def test_verbal_update_counts():
    r = record(documents=[{"date": "2026-07-31", "title": "Committee scheduled a verbal update", "url": None}])
    assert reportbacks.confirmed(r, 0)["url"] is None


def test_table_lists_pending_and_recently_filed_by_adoption(tmp_path):
    folder = tmp_path / "report-backs"
    folder.mkdir()
    cao = {"departments": ["CAO"], "deadline": 30}
    filed = lambda day: [{"date": day, "title": "Report from City Administrative Officer", "url": f"{day}.pdf"}]
    records = {
        "a": {"adopted": "2026-08-20", "documents": [], "requests": [{**cao, "asks": "no deadline", "deadline": None}]},
        "b": {"adopted": "2026-08-19", "documents": [], "requests": [{**cao, "asks": "overdue"}]},
        "c": {"adopted": "2026-03-25", "documents": filed("2026-08-04"), "requests": [{**cao, "asks": "filed"}],
              "document_reviews": {"2026-08-04.pdf": [0]}},
        "d": {"adopted": "2024-03-25", "documents": filed("2024-08-04"), "requests": [{**cao, "asks": "filed long ago"}]},
        "e": {"adopted": None, "documents": [], "requests": [{**cao, "asks": "not adopted"}]},
    }
    for name, r in records.items():
        (folder / f"{name}.json").write_text(json.dumps({"council_file": name, **r}))
    rows = reportbacks.table(date(2026, 10, 4), tmp_path)
    assert [(q["asks"], ok) for _, q, _, ok in rows] == [("no deadline", False), ("overdue", False), ("filed", True)]
    assert [rid for rid, *_ in reportbacks.landed(tmp_path)] == ["report-back:c:0"]


def test_check_record(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"requests": [{"departments": ["CAO"], "asks": "x", "deadline": "soon"}]}))
    assert reportbacks.check_record(path)
    path.write_text(json.dumps({"requests": [{"departments": ["CAO"], "asks": "x", "deadline": "2026-11-01"}]}))
    assert reportbacks.check_record(path) == []
    path.write_text(json.dumps(record(document_reviews={DOT: [1]})))  # there's only request 0
    assert reportbacks.check_record(path)
    path.write_text(json.dumps(record(document_reviews={"elsewhere.pdf": [0]})))
    assert reportbacks.check_record(path)
    path.write_text(json.dumps({"motion": "..."}))  # not reviewed yet
    assert reportbacks.check_record(path) == []
