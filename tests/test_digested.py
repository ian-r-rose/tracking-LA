from tracking_la import digested


def test_items_and_decisions_are_keyed_separately(tmp_path):
    path = tmp_path / "digested.csv"
    digested.append([("2026-10-01", "a", ""), ("2026-10-01", "a", "2026-09-30")], path)
    digested.append([("2026-10-05", "a", "2026-10-04")], path)  # a later decision on the same item
    assert path.read_text().splitlines()[0] == "digest,item_id,decision_recorded"
    assert digested.load(path) == {
        ("a", ""): "2026-10-01", ("a", "2026-09-30"): "2026-10-01", ("a", "2026-10-04"): "2026-10-05",
    }
    assert digested.load(tmp_path / "missing.csv") == {}
