"""
HTTP client compatibility layer using curl_cffi.

This module provides httpx-compatible interfaces using curl_cffi as the backend,
which offers better browser impersonation for Google services.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar
from typing import Any

from curl_cffi import CurlHttpVersion
from curl_cffi.requests import AsyncSession, BrowserTypeLiteral, Cookies, Response


class AsyncClient:
    """
    Async HTTP client using curl_cffi with browser impersonation.

    Provides an httpx-compatible interface while using curl_cffi's
    superior browser fingerprinting capabilities.
    """

    def __init__(
        self,
        *,
        http2: bool = True,
        timeout: float = 30,
        proxy: str | None = None,
        follow_redirects: bool = True,
        headers: dict[str, str] | None = None,
        cookies: Cookies | dict[str, str] | CookieJar | None = None,
        impersonate: BrowserTypeLiteral = "chrome131",
        verify: bool = True,
        **kwargs,
    ):
        self.timeout = timeout
        self.proxy = proxy
        self.follow_redirects = follow_redirects
        self.impersonate = impersonate
        # Skip SSL verification for localhost proxies (useful for debugging with mitmproxy, etc.)
        if proxy and ("localhost" in proxy or "127.0.0.1" in proxy):
            self.verify = False
        else:
            self.verify = verify
        self.http_version = CurlHttpVersion.V2_0 if http2 else CurlHttpVersion.V1_1

        # Store headers
        self._headers = dict(headers) if headers else {}

        # Initialize cookies
        if isinstance(cookies, Cookies):
            self._cookies = cookies
        elif isinstance(cookies, dict):
            self._cookies = Cookies(cookies)
        elif isinstance(cookies, CookieJar):
            self._cookies = Cookies()
            for cookie in cookies:
                if cookie.value is not None:
                    self._cookies.set(cookie.name, cookie.value, domain=cookie.domain)
        else:
            self._cookies = Cookies()

        self._session: AsyncSession | None = None
        self._closed = False

    async def __aenter__(self) -> "AsyncClient":
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.aclose()

    async def _ensure_session(self) -> AsyncSession:
        """Ensure session is initialized."""
        if self._session is None or self._closed:
            self._session = AsyncSession(
                timeout=self.timeout,
                proxy=self.proxy,
                allow_redirects=self.follow_redirects,
                impersonate=self.impersonate,
                verify=self.verify,
                http_version=self.http_version,
            )
            # Set initial cookies
            self._session.cookies = self._cookies
        return self._session

    @property
    def headers(self) -> dict[str, str]:
        """Get headers dictionary."""
        return self._headers

    @property
    def cookies(self) -> Cookies:
        """Get cookies."""
        if self._session:
            return self._session.cookies
        return self._cookies

    @cookies.setter
    def cookies(self, value: Cookies | dict[str, str]) -> None:
        """Set cookies."""
        if isinstance(value, dict):
            value = Cookies(value)
        self._cookies = value
        if self._session:
            self._session.cookies = value

    async def get(self, url: str, **kwargs) -> Response:
        """Send GET request."""
        session = await self._ensure_session()
        headers = {**self._headers, **kwargs.pop("headers", {})}
        return await session.get(url, headers=headers, **kwargs)

    async def post(
        self,
        url: str,
        *,
        content: bytes | str | None = None,
        data: dict[str, Any] | None = None,
        json: Any | None = None,
        files: dict[str, tuple[str, bytes]] | None = None,
        **kwargs,
    ) -> Response:
        """Send POST request."""
        session = await self._ensure_session()
        headers = {**self._headers, **kwargs.pop("headers", {})}

        # curl_cffi uses 'data' for form data and 'json' for JSON
        # For raw content, we need to pass it as 'data' with appropriate content-type
        if content is not None:
            if isinstance(content, str):
                content = content.encode()
            return await session.post(url, headers=headers, data=content, **kwargs)
        elif json is not None:
            return await session.post(url, headers=headers, json=json, **kwargs)
        elif files is not None:
            return await session.post(url, headers=headers, files=files, **kwargs)
        elif data is not None:
            return await session.post(url, headers=headers, data=data, **kwargs)
        else:
            return await session.post(url, headers=headers, **kwargs)

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
        **kwargs,
    ) -> AsyncIterator["StreamResponse"]:
        """
        Stream response data.

        This is an async context manager that yields a StreamResponse object.
        """
        session = await self._ensure_session()
        merged_headers = {**self._headers, **(headers or {})}

        response = await session.request(
            method,
            url,
            params=params,
            headers=merged_headers,
            data=data,
            stream=True,
            **kwargs,
        )

        try:
            yield StreamResponse(response)
        finally:
            pass  # curl_cffi handles cleanup

    async def aclose(self) -> None:
        """Close the client."""
        self._closed = True
        if self._session:
            await self._session.close()
            self._session = None


class StreamResponse:
    """
    Wrapper for streaming response that provides httpx-compatible interface.
    """

    def __init__(self, response: Response):
        self._response = response

    @property
    def status_code(self) -> int:
        """Get response status code."""
        return self._response.status_code

    @property
    def headers(self) -> dict[str, str]:
        """Get response headers."""
        return dict(self._response.headers)

    @property
    def text(self) -> str:
        """Get response text."""
        return self._response.text

    @property
    def content(self) -> bytes:
        """Get response content."""
        return self._response.content

    async def aiter_bytes(self, chunk_size: int | None = None) -> AsyncIterator[bytes]:
        """
        Iterate over response bytes asynchronously.

        Uses curl_cffi's native async content iterator for true streaming.
        """
        async for chunk in self._response.aiter_content():
            yield chunk

    async def aiter_lines(self) -> AsyncIterator[str]:
        """Iterate over response lines asynchronously."""
        text = self._response.text
        for line in text.splitlines():
            yield line
            await asyncio.sleep(0)


class ReadTimeout(Exception):
    """Request timed out while reading response."""

    pass


# Re-export Cookies from curl_cffi
__all__ = ["AsyncClient", "Cookies", "ReadTimeout", "Response", "StreamResponse"]
