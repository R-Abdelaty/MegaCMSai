"""Read-only access to GUC mail through a signed-in OWA browser."""

import os
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

OWA_URL = "https://mail.guc.edu.eg/owa/"
PROFILE_DIR = (
    Path(os.environ.get("LOCALAPPDATA", Path.home()))
    / "GUCmail"
    / "browser-profile"
)


class GUCMail:
    """Retrieve inbox summaries without handling the user's password."""

    def __init__(self):
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._playwright: Playwright = sync_playwright().start()
        self.context: BrowserContext = (
            self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=False,
            )
        )
        self.page: Page = (
            self.context.pages[0] if self.context.pages else self.context.new_page()
        )
        self.page.goto(OWA_URL, wait_until="domcontentloaded")
        self._wait_for_sign_in()

    def _wait_for_sign_in(self) -> None:
        if "/auth/" not in self.page.url.lower():
            return

        print("Sign in to GUC mail in the Chrome window.")
        try:
            self.page.wait_for_url(
                re.compile(r"https://mail\.guc\.edu\.eg/owa/(?!auth/)"),
                timeout=300_000,
            )
        except PlaywrightTimeoutError as error:
            raise RuntimeError("OWA sign-in was not completed within 5 minutes") from error

    def list_recent_emails(
        self,
        limit: int = 10,
        unread_only: bool = False,
    ) -> list[dict]:
        """Return recent inbox summaries without opening or changing messages."""
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")

        try:
            with self.page.expect_response(
                lambda response: (
                    "service.svc" in response.url
                    and "action=FindConversation" in response.url
                ),
                timeout=60_000,
            ) as response_info:
                self.page.reload(wait_until="domcontentloaded")

            response = response_info.value
            if not response.ok:
                raise RuntimeError(
                    f"OWA inbox request failed with HTTP {response.status}"
                )
            payload = response.json()
        except PlaywrightTimeoutError as error:
            raise RuntimeError(
                "OWA did not load an inbox response within 60 seconds"
            ) from error

        conversations = self._find_conversations(payload)
        results = []

        for conversation in conversations:
            unread_count = int(conversation.get("UnreadCount") or 0)
            if unread_only and unread_count == 0:
                continue

            results.append(
                {
                    "id": self._conversation_id(conversation),
                    "subject": conversation.get("ConversationTopic") or "(No subject)",
                    "sender": self._sender_text(conversation),
                    "received": conversation.get("LastDeliveryTime"),
                    "is_read": unread_count == 0,
                    "has_attachments": bool(
                        conversation.get("HasAttachments", False)
                    ),
                    "preview": self._clean_text(conversation.get("Preview"))[:400],
                }
            )
            if len(results) == limit:
                break

        return results

    def close(self) -> None:
        self.context.close()
        self._playwright.stop()

    def __enter__(self) -> "GUCMail":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    @classmethod
    def _find_conversations(cls, value: Any) -> list[dict]:
        if isinstance(value, dict):
            conversations = value.get("Conversations")
            if isinstance(conversations, list):
                return conversations
            for child in value.values():
                found = cls._find_conversations(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = cls._find_conversations(child)
                if found:
                    return found
        return []

    @staticmethod
    def _conversation_id(conversation: dict) -> str | None:
        value = conversation.get("ConversationId")
        if isinstance(value, dict):
            return value.get("Id")
        return str(value) if value else None

    @staticmethod
    def _sender_text(conversation: dict) -> str:
        senders = conversation.get("UniqueSenders") or []
        if not isinstance(senders, list):
            senders = [senders]

        names = []
        for sender in senders:
            if isinstance(sender, dict):
                names.append(
                    sender.get("DisplayName")
                    or sender.get("EmailAddress")
                    or "Unknown"
                )
            elif sender:
                names.append(str(sender))
        return ", ".join(names) or "Unknown"

    @staticmethod
    def _clean_text(value: Any) -> str:
        return " ".join(str(value or "").split())


def main() -> None:
    with GUCMail() as mail:
        for message in mail.list_recent_emails():
            print(
                f"{message['received']} | {message['sender']} | "
                f"{message['subject']}"
            )


if __name__ == "__main__":
    main()
