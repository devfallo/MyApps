#!/usr/bin/env python3
"""Scrape hot posts from m.ppomppu.co.kr and save them as JSON for GitHub Pages."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import List
from urllib.parse import urljoin
from urllib.request import Request, urlopen

SOURCE_URL = "https://m.ppomppu.co.kr/new/index.php"
OUTPUT_PATH = Path("data/ppomppu-hot.json")
MAX_POSTS = 30


@dataclass
class Post:
    title: str
    url: str
    board: str
    author: str
    time: str


class PpomppuHotParser(HTMLParser):
    """Parser tuned for the HOT table used on ppomppu mobile main page."""

    def __init__(self) -> None:
        super().__init__()
        self._posts: List[Post] = []
        self._table_depth = 0
        self._in_row = False
        self._row_links: list[str] = []
        self._row_text: List[str] = []

    @property
    def posts(self) -> List[Post]:
        return self._posts

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)

        if tag == "table" and "table_list" in (attr.get("class") or ""):
            self._table_depth += 1
            return

        if self._table_depth <= 0:
            return

        if tag == "tr":
            self._in_row = True
            self._row_links = []
            self._row_text = []
            return

        if self._in_row and tag == "a":
            href = (attr.get("href") or "").strip()
            if href:
                self._row_links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._table_depth > 0:
            self._table_depth -= 1
            return

        if tag == "tr" and self._in_row:
            self._finalize_row()
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if not self._in_row:
            return
        text = data.strip().replace("\xa0", " ")
        if text:
            self._row_text.append(text)

    def _finalize_row(self) -> None:
        if not self._row_links:
            return

        post_link = ""
        for href in self._row_links:
            if "view.php" in href or "no=" in href:
                post_link = href
                break

        if not post_link:
            return

        # remove noisy markers often mixed in title cells
        text_items = [
            text
            for text in self._row_text
            if text not in {"HOT", "인기", "공지", "새글", "-"} and len(text) >= 2
        ]
        if len(text_items) < 2:
            return

        title = text_items[0]
        board = text_items[1] if len(text_items) > 1 else ""
        author = text_items[2] if len(text_items) > 2 else ""
        post_time = text_items[3] if len(text_items) > 3 else ""

        self._posts.append(
            Post(
                title=title,
                url=urljoin(SOURCE_URL, post_link),
                board=board,
                author=author,
                time=post_time,
            )
        )


def fetch_html_with_urlopen(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
            "Referer": "https://m.ppomppu.co.kr/",
        },
    )
    with urlopen(req, timeout=30) as res:
        raw = res.read()

    for enc in ("euc-kr", "cp949", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def fetch_html_with_playwright(url: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ))
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)
        content = page.content()
        browser.close()
        return content


def scrape_posts() -> tuple[List[Post], str, str]:
    errors: list[str] = []

    try:
        html = fetch_html_with_urlopen(SOURCE_URL)
    except Exception as exc:
        errors.append(f"urlopen: {exc}")
        html = ""

    if not html:
        try:
            html = fetch_html_with_playwright(SOURCE_URL)
        except Exception as exc:
            errors.append(f"playwright: {exc}")

    if not html:
        raise RuntimeError("; ".join(errors) if errors else "failed to fetch source")

    parser = PpomppuHotParser()
    parser.feed(html)
    posts = parser.posts[:MAX_POSTS]

    if not posts:
        raise RuntimeError("parsed 0 posts from fetched html")

    return posts, SOURCE_URL, "; ".join(errors)


def load_previous_posts() -> List[Post]:
    if not OUTPUT_PATH.exists():
        return []
    try:
        payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        return [Post(**item) for item in payload.get("posts", []) if isinstance(item, dict)]
    except Exception:
        return []


def main() -> None:
    previous_posts = load_previous_posts()
    posts: List[Post] = []
    status = "ok"
    error_message = ""

    try:
        posts, _, partial_errors = scrape_posts()
        if partial_errors:
            status = "warning"
            error_message = partial_errors
    except Exception as exc:  # keep workflow resilient
        if previous_posts:
            posts = previous_posts[:MAX_POSTS]
            status = "warning"
            error_message = f"scrape failed, serving last successful data: {exc}"
        else:
            status = "error"
            error_message = str(exc)

    payload = {
        "source": SOURCE_URL,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "error": error_message,
        "count": len(posts),
        "posts": [asdict(p) for p in posts],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
