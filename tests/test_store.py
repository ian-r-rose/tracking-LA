import json

from tracking_la.store import item_path, upsert_item


def item(**fields):
    return {"id": "x", "body": "council", "meeting_date": "2026-10-14", "item_number": "1", "title": "T", "text": "T",
            "urls": [], **fields}


def test_an_item_carries_over_the_extraction_of_the_item_it_follows(tmp_path):
    committee = item(id="council-plum-2026-09-22-1-2", body="council-plum", meeting_date="2026-09-22",
                     summary="Community plan update.", topics=["land_use"], locations=[], details={}, flag={"reason": "r"})
    path = item_path(committee, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(committee))

    assert upsert_item(item(id="council-2026-10-14-9-3", follows=committee["id"]), tmp_path) == "new"
    council = json.loads(item_path(item(id="council-2026-10-14-9-3"), tmp_path).read_text())
    assert council["summary"] == "Community plan update." and council["topics"] == ["land_use"]
    assert "flag" not in council  # whether to list it is the digest's call

    assert upsert_item(item(id="council-2026-10-14-9-4"), tmp_path) == "new"  # follows nothing: left for extraction
    assert "summary" not in json.loads(item_path(item(id="council-2026-10-14-9-4"), tmp_path).read_text())


def test_carry_over_waits_for_the_followed_item(tmp_path):
    from tracking_la.store import carry_over

    committee = item(id="c", body="council-plum")
    path = item_path(committee, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(committee))
    council = item(id="v", follows="c")
    assert carry_over(council, tmp_path) is council  # nothing to carry yet
    path.write_text(json.dumps(committee | {"summary": "s", "topics": ["other"], "locations": []}))
    assert carry_over(council, tmp_path)["summary"] == "s"
