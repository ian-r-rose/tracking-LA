import os
import ssl
import time

import httpx

# Set LACOMM_CONTACT (an email or URL) so site operators can reach us about our traffic.
# The "Mozilla/5.0 (compatible; ...)" prefix is the usual crawler convention; some City sites
# (e.g. Rec & Parks) reject User-Agents without it.
USER_AGENT = "Mozilla/5.0 (compatible; la-commissions/0.1" + (f"; +{c}" if (c := os.environ.get("LACOMM_CONTACT")) else "") + ")"


# Statuses worth another try: City firewalls sometimes refuse a request (403) or a server is
# briefly overloaded (429, 5xx), and the next attempt a little later often succeeds.
RETRY_STATUSES = {403, 429, 500, 502, 503, 504}
RETRY_DELAYS = (5, 20)  # seconds before the second and third attempts


class RetryTransport(httpx.HTTPTransport):
    """Retries connection errors (via httpx) and the statuses above (here)."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for delay in RETRY_DELAYS:
            response = super().handle_request(request)
            if response.status_code not in RETRY_STATUSES:
                return response
            response.close()
            time.sleep(delay)
        return super().handle_request(request)


def http_client(**kwargs) -> httpx.Client:
    # ens.lacity.org only offers ciphers outside Python's default list, but inside OpenSSL's
    # system default (what curl uses), so use that.
    tls = ssl.create_default_context()
    tls.set_ciphers("DEFAULT")
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        verify=tls,
        transport=RetryTransport(verify=tls, retries=2),
        follow_redirects=True,
        **kwargs,
    )
