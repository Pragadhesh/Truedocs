from __future__ import annotations
import re
from base64 import b64encode
from urllib.parse import urlparse
import httpx


class ConfluenceClient:
    def __init__(self, url: str, email: str, token: str):
        self.base_url = url.rstrip("/")
        encoded = b64encode(f"{email}:{token}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
        }

    @classmethod
    def from_credentials_and_page_url(
        cls, creds: dict, page_url: str
    ) -> "ConfluenceClient":
        return cls(
            url=cls._extract_base_url(page_url),
            email=creds["confluence_email"],
            token=creds["confluence_token"],
        )

    def can_access_page(self, page_url: str) -> bool:
        return self.get_page(page_url) is not None

    def get_page(self, page_url: str) -> dict | None:
        """Fetch a Confluence page's storage-format body by its URL."""
        page_id = self._page_id(page_url)
        if not page_id:
            return None
        try:
            r = httpx.get(
                f"{self.base_url}/api/v2/pages/{page_id}",
                params={"body-format": "storage"},
                headers={**self._headers, "Cache-Control": "no-cache"},
                timeout=5,
            )
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    def update_page_with_html(self, page_url: str, new_html: str) -> bool:
        """Replace the Confluence page body with new Storage Format HTML. Returns True on success."""
        page_id = self._page_id(page_url)
        if not page_id:
            return False
        try:
            r = httpx.get(
                f"{self.base_url}/api/v2/pages/{page_id}",
                headers={**self._headers, "Cache-Control": "no-cache"},
                timeout=10,
            )
            if r.status_code != 200:
                return False
            page = r.json()
            current_version = page.get("version", {}).get("number", 1)
            title = page.get("title", "TrueDocs")

            payload = {
                "id": page_id,
                "status": "current",
                "title": title,
                "body": {"representation": "storage", "value": new_html},
                "version": {
                    "number": current_version + 1,
                    "message": "(TrueDocs) drift approved via Slack",
                },
            }
            resp = httpx.put(
                f"{self.base_url}/api/v2/pages/{page_id}",
                headers={**self._headers, "Content-Type": "application/json"},
                json=payload,
                timeout=15,
            )
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _extract_base_url(page_url: str) -> str:
        """Extract Confluence base URL from a full page URL.

        Cloud:     https://host/wiki/spaces/...  -> https://host/wiki
        Server/DC: https://host/display/...      -> https://host
        """
        parsed = urlparse(page_url)
        path = parsed.path
        wiki_idx = path.find("/wiki")
        if wiki_idx != -1:
            base_path = path[: wiki_idx + 5]
        else:
            base_path = ""
        return f"{parsed.scheme}://{parsed.netloc}{base_path}"

    @staticmethod
    def _page_id(url: str) -> str | None:
        m = re.search(r"/pages/(\d+)", url)
        return m.group(1) if m else None
