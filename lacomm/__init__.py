import os
import ssl

import httpx

# Set LACOMM_CONTACT (an email or URL) so site operators can reach us about our traffic.
USER_AGENT = "la-commissions/0.1" + (f" ({c})" if (c := os.environ.get("LACOMM_CONTACT")) else "")


def http_client(**kwargs) -> httpx.Client:
    # ens.lacity.org only offers ciphers outside Python's default list, but inside OpenSSL's
    # system default (what curl uses), so use that.
    tls = ssl.create_default_context()
    tls.set_ciphers("DEFAULT")
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        verify=tls,
        transport=httpx.HTTPTransport(verify=tls, retries=2),  # retries connection errors only
        follow_redirects=True,
        **kwargs,
    )
