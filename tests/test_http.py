import httpx

import tracking_la


def test_retries_transient_statuses(monkeypatch):
    statuses = iter([403, 503, 200])
    calls = []

    def fake(self, request):
        calls.append(request.url)
        return httpx.Response(next(statuses))

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake)
    monkeypatch.setattr(tracking_la, "RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(tracking_la.time, "sleep", lambda s: None)
    with tracking_la.http_client() as client:
        assert client.get("https://example.org/").status_code == 200
    assert len(calls) == 3


def test_gives_up_after_three_attempts_and_skips_other_errors(monkeypatch):
    calls = []

    def fake(self, request):
        calls.append(1)
        return httpx.Response(403 if len(calls) < 10 else 200)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake)
    monkeypatch.setattr(tracking_la.time, "sleep", lambda s: None)
    with tracking_la.http_client() as client:
        assert client.get("https://example.org/").status_code == 403
    assert len(calls) == 3

    calls.clear()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda self, r: calls.append(1) or httpx.Response(404))
    with tracking_la.http_client() as client:
        assert client.get("https://example.org/").status_code == 404
    assert len(calls) == 1
