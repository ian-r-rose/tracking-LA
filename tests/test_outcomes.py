import json
from datetime import date
from pathlib import Path

from tracking_la.outcomes import normalize_status, record
from tracking_la.sources import primegov, rap

FIXTURES = Path(__file__).parent / "fixtures"


def test_normalize_status():
    assert normalize_status("REPORT ADOPTED, SUBJECT TO CONDITIONS, FORTHWITH") == "approved"
    assert normalize_status("CONTINUED DATE TO BE DETERMINED.") == "continued"
    assert normalize_status("WITHDRAWN") == "withdrawn"
    assert normalize_status("RECEIVED AND FILED") == "filed"
    assert normalize_status("BIDS RECEIVED, OPENED AND DECLARED, FORTHWITH") == "filed"
    assert normalize_status("DENIED") == "denied"
    assert normalize_status("TAKEN UNDER SUBMISSION") == "other"


def test_public_works_journal():
    meeting = {"body": "bpw", "date": date(2026, 9, 9), "meeting_id": 2826, "journal_url": "J"}
    outcomes = primegov.journal_outcomes(meeting, (FIXTURES / "primegov" / "bpw-journal-2026-09-09.html").read_bytes())
    assert outcomes["bpw-2026-09-09-2826-9"] == {
        "text": "REPORT ADOPTED, SUBJECT TO CONDITIONS, FORTHWITH", "source": "J", "vote": "5-0",
    }
    assert outcomes["bpw-2026-09-09-2826-10"] == {"text": "CONTINUED DATE TO BE DETERMINED.", "source": "J"}


def test_rec_and_parks_minutes():
    meeting = {"date": date(2026, 9, 17), "minutes_url": "M"}
    outcomes = rap.minutes_outcomes(meeting, (FIXTURES / "rap" / "minutes-2026-09-17.txt").read_text())
    assert len(outcomes) == 11
    assert outcomes["rap-2026-09-17-26-213"] == {"text": "APPROVED", "source": "M", "vote": "5-0"}
    # Withdrawn before any vote.
    assert outcomes["rap-2026-09-17-26-210"] == {"text": "WITHDRAWN", "source": "M"}


def test_record_is_idempotent(tmp_path):
    path = tmp_path / "item.json"
    path.write_text(json.dumps({"id": "x"}))
    outcome = {"status": "approved", "text": "APPROVED", "source": "M", "vote": "5-0"}
    assert record(path, outcome)
    assert not record(path, outcome)
    assert json.loads(path.read_text())["outcome"]["vote"] == "5-0"
