"""
Exceptions for the CF Browser SDK.
"""


class CFBrowserError(Exception):
    """Base exception for all CF Browser errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(CFBrowserError):
    """Raised when the API key is invalid or missing (HTTP 401)."""


class RateLimitError(CFBrowserError):
    """Raised when the rate limit is exceeded (HTTP 429)."""


class NotFoundError(CFBrowserError):
    """Raised when the requested resource is not found (HTTP 404)."""
