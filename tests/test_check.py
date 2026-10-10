from tracking_la.check import check_digest


def test_digest_bullets_need_a_link(tmp_path):
    digest = tmp_path / "2026-10-08.md"
    digest.write_text(
        "## Board\n\nWhat it does.\n\n"
        "- **Sep 22** · citywide — A ban: **approved**.\n"
        "- **Sep 23** · Van Nuys — Five leases:\n"
        "  - **Joby**: 10 years.\n\n"
        "  [Agenda](https://example.org/agenda)\n"
        "- **Sep 8** · Downtown — A fund. [Council File 22-0708-S3](https://example.org/cf)\n"
    )
    assert check_digest(digest) == ["bullet without a link: - **Sep 22** · citywide — A ban: **approved**."]
