from tracking_la.site import build


def test_build(tmp_path):
    out = tmp_path / "site"
    n = build(out)
    assert n == len(list((out / "digests").glob("*.html")))
    index = (out / "index.html").read_text()
    assert "<h1>Commissions digest" in index and 'href="style.css"' in index
    assert "<table>" in (out / "commissions.html").read_text()
    assert "title: " not in (out / "commissions.html").read_text()  # front matter stripped
