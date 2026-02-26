import logging
import unittest
from pathlib import Path

from gemini_webapi import GeminiClient, logger, set_log_level
from gemini_webapi.types.image import HTTPError
from gemini_webapi.utils import load_netscape_cookies_as_dict

logging.getLogger("asyncio").setLevel(logging.ERROR)
set_log_level("DEBUG")


class TestGeminiClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cookies = load_netscape_cookies_as_dict(Path(__file__).parent.parent / "cookies.txt", domain_filter=".google.com")
        proxy = "http://localhost:8000"
        self.geminiclient = GeminiClient(cookies.get("__Secure-1PSID"), cookies.get("__Secure-1PSIDTS"))
        await self.geminiclient.init(auto_refresh=False)

    async def test_save_web_image(self):
        response = await self.geminiclient.generate_content("Show me some pictures of random subjects")
        self.assertTrue(response.images)
        for image in response.images:
            try:
                await image.save(verbose=True, skip_invalid_filename=True)
            except HTTPError as e:
                logger.warning(e)

    async def test_save_generated_image(self):
        response = await self.geminiclient.generate_content("Generate a picture of random subjects")
        self.assertTrue(response.images)
        for image in response.images:
            await image.save(verbose=True, full_size=True)

    async def test_save_image_to_image(self):
        response = await self.geminiclient.generate_content(
            "Design an application icon based on the provided image. Make it simple and modern.",
            files=["assets/banner.png"],
        )
        self.assertTrue(response.images)
        for image in response.images:
            await image.save(verbose=True, full_size=True)


if __name__ == "__main__":
    unittest.main()
