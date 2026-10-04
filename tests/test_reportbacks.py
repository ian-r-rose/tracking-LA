import json
from datetime import date
from pathlib import Path

from tracking_la import reportbacks

FIXTURES = Path(__file__).parent / "fixtures" / "council"


def test_page_gives_motion_adoption_and_documents_filed_after():
    page = reportbacks.parse_page((FIXTURES / "cf-26-0251.html").read_text())
    assert page["title"].startswith("Interstate 110 / Gaffey Street")
    assert page["introduced"] == "2026-02-20" and page["adopted"] == "2026-03-25"
    assert page["motion_url"].endswith("26-0251_misc_02-20-26.pdf")
    assert page["documents"] == [{"date": "2026-08-04", "from": "Department of Transportation"}]


def test_submitters():
    assert reportbacks.submitters("Document submitted by Bureau of Sanitation, dated September 15, 2026.") == ["Bureau of Sanitation"]
    assert reportbacks.submitters("Document submitted by the Mayor, City Administrative Officer report dated July 16, 2026.") == [
        "City Administrative Officer"
    ]
    assert reportbacks.submitters("Document(s) submitted by Bureau of Street Services; Department of Transportation") == [
        "Bureau of Street Services", "Department of Transportation",
    ]
    assert reportbacks.submitters(
        "Housing and Homelessness Committee scheduled a verbal update for this matter pursuant to Council action of July 1, 2025."
    ) == ["verbal update"]
    assert reportbacks.submitters("Council action final.") == []


def test_operative_text_starts_at_the_move_paragraphs():
    text = "Background about the incident.\n\nI THEREFORE MOVE that LADOT report back within 30 days."
    assert reportbacks.operative_text(text) == "I THEREFORE MOVE that LADOT report back within 30 days."


def test_filed_due_and_table():
    late = {"council_file": "26-0251", "adopted": "2026-03-25",
            "documents": [{"date": "2026-08-04", "from": "Department of Transportation"}],
            "requests": [{"departments": ["LADOT"], "asks": "Incident response", "deadline": 30}]}
    old = {"council_file": "24-0001", "adopted": "2024-01-01",
           "documents": [{"date": "2024-03-01", "from": "Department of Transportation"}],
           "requests": [{"departments": ["Department of Transportation"], "asks": "z", "deadline": "2024-02-01"}]}
    assert reportbacks.filed(late, late["requests"][0])["date"] == "2026-08-04"  # LADOT is the Department of Transportation
    assert reportbacks.due(late, late["requests"][0]) == date(2026, 4, 24)
    assert reportbacks.due(old, old["requests"][0]) == date(2024, 2, 1)


def test_table_lists_pending_then_recently_filed(tmp_path, monkeypatch):
    folder = tmp_path / "report-backs"
    folder.mkdir()
    records = {
        "a": {"adopted": "2026-08-19", "documents": [], "requests": [{"departments": ["CAO"], "asks": "no deadline", "deadline": None}]},
        "b": {"adopted": "2026-08-19", "documents": [], "requests": [{"departments": ["CAO"], "asks": "overdue", "deadline": 30}]},
        "c": {"adopted": "2026-03-25", "documents": [{"date": "2026-08-04", "from": "City Administrative Officer"}],
              "requests": [{"departments": ["CAO"], "asks": "filed", "deadline": 30}]},
        "d": {"adopted": "2024-03-25", "documents": [{"date": "2024-08-04", "from": "City Administrative Officer"}],
              "requests": [{"departments": ["CAO"], "asks": "filed long ago", "deadline": 30}]},
        "e": {"adopted": None, "documents": [], "requests": [{"departments": ["CAO"], "asks": "not adopted", "deadline": 30}]},
    }
    for name, r in records.items():
        (folder / f"{name}.json").write_text(json.dumps({"council_file": name, **r}))
    rows = reportbacks.table(date(2026, 10, 4), tmp_path)
    assert [q["asks"] for _, q, _ in rows] == ["overdue", "no deadline", "filed"]


def test_check_record(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"requests": [{"departments": ["CAO"], "asks": "x", "deadline": "soon"}]}))
    assert reportbacks.check_record(path)
    path.write_text(json.dumps({"requests": [{"departments": ["CAO"], "asks": "x", "deadline": "2026-11-01"}]}))
    assert reportbacks.check_record(path) == []
    path.write_text(json.dumps({"motion": "..."}))  # not reviewed yet
    assert reportbacks.check_record(path) == []
