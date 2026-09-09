"""One JSON POST helper shared by the real providers.

Keeps the three provider modules to the part that actually differs: the URL,
the auth header, the request body, and where the text sits in the response.
"""

from __future__ import annotations

import requests

from .base import ProviderError

# Generous enough for a slow model, short enough that a hung call fails.
HTTP_TIMEOUT_SECONDS = 60


def post_json(
    url: str,
    headers: dict[str, str],
    payload: dict,
    provider: str,
    timeout: int = HTTP_TIMEOUT_SECONDS,
) -> dict:
    """POST JSON and return the decoded body, or raise one readable sentence."""
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.Timeout:
        raise ProviderError(f"{provider} did not respond within {timeout} seconds.") from None
    except requests.RequestException as exc:
        raise ProviderError(f"{provider} request failed: {exc}") from None

    if response.status_code >= 400:
        detail = " ".join(response.text.split())[:300]
        raise ProviderError(
            f"{provider} returned HTTP {response.status_code}: {detail}"
        )
    try:
        return response.json()
    except ValueError:
        raise ProviderError(f"{provider} returned a response that was not JSON.") from None
