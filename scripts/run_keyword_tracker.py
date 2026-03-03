#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "keyword-tracker.json"


def fetch_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any]) -> None:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15):
        return


def load_previous() -> dict[str, Any]:
    if OUTPUT_PATH.exists():
        return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    return {"seenUrls": [], "matchHistory": []}


def fetch_ppomppu_hot() -> list[dict[str, str]]:
    local_path = ROOT / "data" / "ppomppu-hot.json"
    if not local_path.exists():
        return []
    data = json.loads(local_path.read_text(encoding="utf-8"))
    return [{"source":"뽐뿌 HOT","title":i.get("title",""),"url":i.get("url",""),"content":" ".join([i.get("board",""), i.get("author","")])} for i in data.get("posts",[])[:20]]


def fetch_hacker_news() -> list[dict[str, str]]:
    data = fetch_json("https://hn.algolia.com/api/v1/search?tags=front_page")
    posts=[]
    for item in data.get("hits", [])[:20]:
        title = item.get("title") or item.get("story_title")
        if not title:
            continue
        posts.append({"source":"Hacker News","title":title,"url":item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID')}","content":(item.get("story_text") or "")[:500]})
    return posts


def fetch_github_discussions() -> list[dict[str, str]]:
    q = urllib.parse.quote("AI OR NAS OR action camera")
    data = fetch_json(f"https://api.github.com/search/issues?q={q}&sort=updated&order=desc&per_page=20", headers={"User-Agent":"MyAppsKeywordBot/1.0"})
    posts=[]
    for item in data.get("items", []):
        posts.append({"source":"GitHub Issues","title":item.get("title",""),"url":item.get("html_url",""),"content":(item.get("body") or "")[:500]})
    return posts


def keyword_list() -> list[str]:
    raw = os.getenv("TRACK_KEYWORDS", "액션캠,NAS,특가,AI,LLM")
    return [k.strip() for k in raw.split(",") if k.strip()]


def find_matches(posts: list[dict[str, str]], keywords: list[str]) -> list[dict[str, Any]]:
    out=[]
    now = datetime.now(timezone.utc).isoformat()
    for post in posts:
        hay = f"{post['title']} {post.get('content','')}".lower()
        found=[k for k in keywords if k.lower() in hay]
        if found:
            out.append({"detectedAt":now,"source":post["source"],"title":post["title"],"url":post["url"],"keywords":found})
    return out


def send_notifications(new_matches: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not new_matches:
        return []
    lines=["🔔 MyApps 키워드 알림"]
    for m in new_matches[:8]:
        lines.append(f"- [{','.join(m['keywords'])}] {m['title']} ({m['source']})")
        lines.append(f"  {m['url']}")
    message="\n".join(lines)

    sent=[]
    webhook = os.getenv("KEYWORD_WEBHOOK_URL")
    if webhook:
        try:
            post_json(webhook, {"text":message})
            sent.append({"channel":"webhook","status":"sent"})
        except Exception as exc:
            sent.append({"channel":"webhook","status":f"error: {exc}"})

    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            post_json(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id":chat,"text":message})
            sent.append({"channel":"telegram","status":"sent"})
        except Exception as exc:
            sent.append({"channel":"telegram","status":f"error: {exc}"})

    if not sent:
        sent.append({"channel":"none","status":"skipped(no webhook configured)"})
    return sent


def keyword_stats(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    c = Counter()
    for row in history:
        for kw in row.get("keywords",[]):
            c[kw]+=1
    return [{"keyword":k,"count":v} for k,v in c.most_common(10)]


def main() -> None:
    prev = load_previous()
    seen = set(prev.get("seenUrls", []))
    history = prev.get("matchHistory", [])

    posts=[]
    errors=[]
    for fn in (fetch_ppomppu_hot, fetch_hacker_news, fetch_github_discussions):
        try:
            posts.extend(fn())
        except Exception as exc:
            errors.append(f"{fn.__name__}: {exc}")

    matches = find_matches(posts, keyword_list())
    new_matches=[m for m in matches if m.get("url") and m["url"] not in seen]
    for m in new_matches:
        seen.add(m["url"])

    notifications=send_notifications(new_matches)
    history=(new_matches + history)[:200]

    payload={
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "keywords": keyword_list(),
        "scannedCount": len(posts),
        "newMatchCount": len(new_matches),
        "matchHistory": history,
        "keywordStats": keyword_stats(history),
        "notifications": notifications,
        "seenUrls": sorted(seen),
        "errors": errors,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} with {len(new_matches)} new matches")


if __name__ == "__main__":
    main()
