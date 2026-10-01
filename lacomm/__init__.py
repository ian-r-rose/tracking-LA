import os

# Set LACOMM_CONTACT (an email or URL) so site operators can reach us about our traffic.
USER_AGENT = "la-commissions/0.1" + (f" ({c})" if (c := os.environ.get("LACOMM_CONTACT")) else "")
