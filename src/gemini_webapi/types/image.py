import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from ..http_client import AsyncClient, Cookies
from ..utils import logger


class HTTPError(Exception):
    """HTTP error for compatibility."""

    pass


class Image(BaseModel):
    """
    A single image object returned from Gemini.

    Parameters
    ----------
    url: `str`
        URL of the image.
    title: `str`, optional
        Title of the image, by default is "[Image]".
    alt: `str`, optional
        Optional description of the image.
    proxy: `str`, optional
        Proxy used when saving image.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str
    title: str = "[Image]"
    alt: str = ""
    proxy: str | None = None

    def __str__(self):
        return f"Image(title='{self.title}', alt='{self.alt}', url='{(len(self.url) <= 20 and self.url) or self.url[:8] + '...' + self.url[-12:]}')"

    async def save(
        self,
        path: str = "temp",
        filename: str | None = None,
        cookies: dict | Cookies | None = None,
        verbose: bool = False,
        skip_invalid_filename: bool = False,
    ) -> str | None:
        """
        Save the image to disk.

        Parameters
        ----------
        path: `str`, optional
            Path to save the image, by default will save to "./temp".
        filename: `str`, optional
            File name to save the image, by default will use the original file name from the URL.
        cookies: `dict`, optional
            Cookies used for requesting the content of the image.
        verbose : `bool`, optional
            If True, will print the path of the saved file or warning for invalid file name, by default False.
        skip_invalid_filename: `bool`, optional
            If True, will only save the image if the file name and extension are valid, by default False.

        Returns
        -------
        `str | None`
            Absolute path of the saved image if successful, None if filename is invalid and `skip_invalid_filename` is True.

        Raises
        ------
        `httpx.HTTPError`
            If the network request failed.
        """

        filename = filename or self.url.split("/")[-1].split("?")[0]
        match = re.search(r"^(.*\.\w+)", filename)
        if match:
            filename = match.group()
        else:
            if verbose:
                logger.warning(f"Invalid filename: {filename}")
            if skip_invalid_filename:
                return None

        headers = {
            "Origin": "https://gemini.google.com",
            "Referer": "https://gemini.google.com/",
        }
        # Add authuser param for Google image URLs
        download_url = self.url
        if "googleusercontent.com" in download_url and "?" not in download_url:
            download_url += "?authuser=0"

        # Copy cookies with additional domains for Google image CDN
        download_cookies = Cookies()
        if cookies:
            if isinstance(cookies, dict):
                # Dict cookies - set for both google.com and usercontent.google.com
                for name, value in cookies.items():
                    download_cookies.set(name, value, domain=".google.com")
                    download_cookies.set(name, value, domain=".usercontent.google.com")
            elif hasattr(cookies, "jar"):
                # Cookies object with jar attribute
                for cookie in cookies.jar:
                    download_cookies.set(cookie.name, cookie.value, domain=cookie.domain)
                    if cookie.domain and "google.com" in cookie.domain:
                        download_cookies.set(cookie.name, cookie.value, domain=".usercontent.google.com")
            else:
                # Assume it's already a Cookies object, copy it
                download_cookies = cookies

        async with AsyncClient(http2=True, follow_redirects=True, headers=headers, cookies=download_cookies, proxy=self.proxy) as client:
            # Follow text-based redirect chain (Google returns URLs in response body)
            current_url = download_url
            max_redirects = 5
            response = None
            for _ in range(max_redirects):
                response = await client.get(current_url)
                if response.status_code != 200:
                    break
                content_type = response.headers.get("content-type", "")
                if "image" in content_type:
                    break
                if content_type.startswith("text/plain"):
                    # Response body contains redirect URL
                    new_url = response.text.strip()
                    if new_url.startswith("http"):
                        current_url = new_url
                    else:
                        break
                else:
                    break

            if response is not None and response.status_code == 200 and "image" in response.headers.get("content-type", ""):
                content_type = response.headers.get("content-type")
                if content_type and "image" not in content_type:
                    logger.warning(f"Content type of {filename} is not image, but {content_type}.")

                path = Path(path)
                path.mkdir(parents=True, exist_ok=True)

                dest = path / filename
                dest.write_bytes(response.content)

                if verbose:
                    logger.info(f"Image saved as {dest.resolve()}")

                return str(dest.resolve())
            else:
                reason = getattr(response, "reason_phrase", None) or getattr(response, "reason", "") or ""
                raise HTTPError(f"Error downloading image: {response.status_code} {reason}")


class WebImage(Image):
    """
    Image retrieved from web. Returned when ask Gemini to "SEND an image of [something]".
    """

    pass


class GeneratedImage(Image):
    """
    Image generated by ImageFX, Google's AI image generator. Returned when ask Gemini to "GENERATE an image of [something]".

    Parameters
    ----------
    cookies: `dict | httpx.Cookies`
        Cookies used for requesting the content of the generated image, inherit from GeminiClient object or manually set.
        Should contain valid "__Secure-1PSID" and "__Secure-1PSIDTS" values.
    """

    cookies: dict[str, str] | Cookies

    @field_validator("cookies", mode="after")
    @classmethod
    def validate_cookies(cls, v: dict[str, str] | Cookies) -> dict[str, str] | Cookies:
        if len(v) == 0:
            raise ValueError("GeneratedImage is designed to be initialized with same cookies as GeminiClient.")
        return v

    # @override
    async def save(
        self,
        path: str = "temp",
        filename: str | None = None,
        cookies: dict | Cookies | None = None,
        verbose: bool = False,
        skip_invalid_filename: bool = False,
        full_size: bool = True,
    ) -> str | None:
        """
        Save the image to disk.

        Parameters
        ----------
        path: `str`, optional
            Path to save the image, by default will save to "./temp".
        filename: `str`, optional
            Filename to save the image, generated images are always in .png format, but file extension will not be included in the URL.
            And since the URL ends with a long hash, by default will use timestamp + end of the hash as the filename.
        cookies: `dict`, optional
            Cookies used for requesting the content of the image. If not provided, will use the cookies from the GeneratedImage instance.
        verbose : `bool`, optional
            If True, will print the path of the saved file or warning for invalid file name, by default False.
        skip_invalid_filename: `bool`, optional
            If True, will only save the image if the file name and extension are valid, by default False.
        full_size: `bool`, optional
            If True, will modify the default preview (512*512) URL to get the full size image, by default True.

        Returns
        -------
        `str | None`
            Absolute path of the saved image if successfully saved.
        """

        if full_size:
            self.url += "=s2048"

        return await super().save(
            path=path,
            filename=filename or f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{self.url[-10:]}.png",
            cookies=cookies or self.cookies,
            verbose=verbose,
            skip_invalid_filename=skip_invalid_filename,
        )
