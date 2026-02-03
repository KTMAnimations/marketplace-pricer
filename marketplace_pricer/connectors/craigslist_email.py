from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass
from email.message import Message
from typing import Any

from bs4 import BeautifulSoup

from marketplace_pricer.connectors.base import Listing
from marketplace_pricer.db import WatchlistRow
from marketplace_pricer.normalization import normalize_whitespace, parse_usd_to_cents


_CL_URL_RE = re.compile(r"https?://[a-z0-9.-]+craigslist\.org/[^\s\"'<>]+", re.IGNORECASE)


@dataclass(frozen=True)
class ImapConfig:
    host: str
    username: str
    password: str
    folder: str = "INBOX"


class CraigslistSavedSearchEmailConnector:
    source = "craigslist_email"

    def __init__(self, imap: ImapConfig):
        self._imap = imap

    def scan(self, watchlist: WatchlistRow) -> list[Listing]:
        filters = watchlist.filters
        from_addr = str(filters.get("from_addr", "notifications@craigslist.org"))
        subject_contains = filters.get("subject_contains")

        query_fragments = [f'FROM "{from_addr}"']
        if subject_contains:
            query_fragments.append(f'SUBJECT "{subject_contains}"')
        # UNSEEN keeps the mailbox as the state/dedupe mechanism (Craigslist already does the alert filtering).
        query_fragments.append("UNSEEN")
        search_query = "(" + " ".join(query_fragments) + ")"

        out: list[Listing] = []
        with imaplib.IMAP4_SSL(self._imap.host) as imap:
            imap.login(self._imap.username, self._imap.password)
            imap.select(self._imap.folder)
            status, data = imap.search(None, search_query)
            if status != "OK" or not data or not data[0]:
                return []

            ids = data[0].split()
            # Limit per scan to avoid large backfills on first run
            max_emails = int(filters.get("max_emails", 25))
            for msg_id in ids[-max_emails:]:
                status, msg_data = imap.fetch(msg_id, "(RFC822)")
                if status != "OK" or not msg_data:
                    continue
                raw_bytes = msg_data[0][1]
                msg = email.message_from_bytes(raw_bytes)
                out.extend(_extract_listings_from_message(msg, watchlist=watchlist))

                # Mark as seen so we don't re-alert next run.
                imap.store(msg_id, "+FLAGS", "\\Seen")

        # De-dupe by URL
        unique: dict[str, Listing] = {}
        for listing in out:
            unique[listing.url] = listing
        return list(unique.values())


def _message_body_html(msg: Message) -> str | None:
    if msg.is_multipart():
        for preferred_type in ("text/html", "text/plain"):
            for part in msg.walk():
                if part.get_content_type() != preferred_type:
                    continue
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return None
    payload = msg.get_payload(decode=True)
    if not payload:
        return None
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def _extract_listings_from_message(msg: Message, *, watchlist: WatchlistRow) -> list[Listing]:
    body = _message_body_html(msg) or ""
    soup = BeautifulSoup(body, "html.parser")
    text = soup.get_text("\n")
    urls = set(_CL_URL_RE.findall(body) + _CL_URL_RE.findall(text))

    subject = normalize_whitespace(str(msg.get("Subject", "")))
    price_cents = parse_usd_to_cents(subject or "")

    out: list[Listing] = []
    for url in urls:
        out.append(
            Listing(
                source="craigslist_email",
                external_id=None,
                url=url,
                title=subject,
                price_cents=price_cents,
                currency="USD",
                location=None,
                seller=None,
                raw={"subject": subject, "watchlist_id": watchlist.id},
            )
        )
    return out
