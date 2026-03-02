#!/usr/bin/env python3
"""Scrape hot posts from m.ppomppu.co.kr and save them as JSON for GitHub Pages."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import List
from urllib.parse import urljoin
from urllib.request import Request, urlopen

SOURCE_URL = "https://m.ppomppu.co.kr/new/index.php"
OUTPUT_PATH = Path("data/ppomppu-hot.json")


@dataclass
class Post:
    title: str
    url: str
    board: str
    author: str
    time: str


class PpomppuHotParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._posts: List[Post] = []
        self._in_hot_table = False
        self._in_row = False
        self._row_links: list[tuple[str, str]] = []
        self._row_text: List[str] = []

    @property
    def posts(self) -> List[Post]:
        return self._posts

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "table" and "table_list" in (attr.get("class") or ""):
            self._in_hot_table = True
            return

        if not self._in_hot_table:
            return

        if tag == "tr":
            self._in_row = True
            self._row_links = []
            self._row_text = []

        if self._in_row and tag == "a":
            href = attr.get("href") or ""
            cls = attr.get("class") or ""
            self._row_links.append((href, cls))

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_hot_table:
            self._in_hot_table = False
            return

        if tag == "tr" and self._in_row:
            self._finalize_row()
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_row:
            text = data.strip()
            if text:
                self._row_text.append(text)

    def _finalize_row(self) -> None:
        if not self._row_links:
            return

        title_link = ""
        for href, cls in self._row_links:
            if "article" in href or "no=" in href:
                title_link = href
                break
        if not title_link:
            title_link = self._row_links[-1][0]

        title_candidates = [text for text in self._row_text if len(text) > 2]
        if not title_candidates:
            return

        title = title_candidates[0]
        board = title_candidates[1] if len(title_candidates) > 1 else ""
        author = title_candidates[2] if len(title_candidates) > 2 else ""
        post_time = title_candidates[3] if len(title_candidates) > 3 else ""

        self._posts.append(
            Post(
                title=title,
                url=urljoin(SOURCE_URL, title_link),
                board=board,
                author=author,
                time=post_time,
            )
        )


def fetch_html(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        },
    )
    with urlopen(req, timeout=20) as res:
        raw = res.read()

    # site is usually euc-kr; decode with fallback
    for enc in ("euc-kr", "cp949", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def main() -> None:
    posts: List[Post] = []
    status = "ok"
    error_message = ""

    try:
        html = fetch_html(SOURCE_URL)
        parser = PpomppuHotParser()
        parser.feed(html)
        posts = parser.posts[:30]
        if not posts:
            status = "warning"
            error_message = "No posts parsed from source HTML."
    except Exception as exc:  # keep workflow resilient
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
