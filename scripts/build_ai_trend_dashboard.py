#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "ai-trend-dashboard.json"

STOPWORDS = {"the","and","for","with","that","this","from","into","about","your","have","has","are","was","will","its","new","you","how","why","what","when","where","who","a","an","to","of","in","on","by","at","is","be","it","as"}


def fetch_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers or {}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def fetch_hn() -> list[dict[str, Any]]:
    data = fetch_json("https://hn.algolia.com/api/v1/search?tags=front_page")
    out = []
    for item in data.get("hits", [])[:15]:
        title = item.get("title") or item.get("story_title")
        if not title:
            continue
        out.append({"source":"Hacker News","title":title,"url":item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID')}","score":item.get("points",0),"comments":item.get("num_comments",0),"text":item.get("story_text") or item.get("comment_text") or ""})
    return out


def fetch_github_hot() -> list[dict[str, Any]]:
    q = urllib.parse.quote("topic:ai stars:>1000")
    data = fetch_json(f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=12", headers={"User-Agent":"MyAppsTrendBot/1.0"})
    out = []
    for repo in data.get("items", []):
        out.append({"source":"GitHub Repos","title":repo.get("full_name",""),"url":repo.get("html_url",""),"score":repo.get("stargazers_count",0),"comments":repo.get("open_issues_count",0),"text":repo.get("description") or ""})
    return out


def fetch_reddit() -> list[dict[str, Any]]:
    data = fetch_json("https://www.reddit.com/r/programming/hot.json?limit=12", headers={"User-Agent":"MyAppsTrendBot/1.0"})
    out=[]
    for child in data.get("data",{}).get("children",[]):
        item = child.get("data",{})
        title=item.get("title")
        if not title:
            continue
        out.append({"source":"Reddit /r/programming","title":title,"url":"https://reddit.com"+item.get("permalink",""),"score":item.get("score",0),"comments":item.get("num_comments",0),"text":item.get("selftext","")})
    return out


def call_llm_summary(text: str) -> str | None:
    api_url = os.getenv("LLM_API_URL")
    if not api_url:
        return None
    headers = {"Content-Type":"application/json"}
    if os.getenv("LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.getenv('LLM_API_KEY')}"
    try:
        data = post_json(api_url, {"prompt":"다음 기술 이슈를 한국어 3~4줄로 요약해줘.\n"+text[:3000]}, headers=headers)
        return data.get("summary") or data.get("text") or data.get("output")
    except Exception:
        return None


def extractive_summary(item: dict[str, Any]) -> str:
    base = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", f"{item['title']}. {item.get('text','')}"))
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", base) if len(s.strip()) > 20][:3]
    if not sents:
        sents = [base[:260]]
    return " ".join(sents + [f"점수 {item.get('score',0)}, 반응 {item.get('comments',0)} 기준 인기 이슈입니다."])


def extract_keywords(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    c = Counter()
    for post in posts:
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9+\-]{2,}", f"{post['title']} {post.get('text','')}".lower())
        for w in words:
            if w not in STOPWORDS:
                c[w] += 1
    return [{"keyword":k,"count":v} for k,v in c.most_common(15)]


def main() -> None:
    posts=[]
    errors=[]
    for fn in (fetch_hn, fetch_github_hot, fetch_reddit):
        try:
            posts.extend(fn())
        except Exception as exc:
            errors.append(f"{fn.__name__}: {exc}")
    ranked = sorted(posts, key=lambda x:(x.get("score",0),x.get("comments",0)), reverse=True)[:25]
    for item in ranked:
        item["summary"] = call_llm_summary(f"[{item['source']}] {item['title']}\n{item.get('text','')}") or extractive_summary(item)
    payload = {"updatedAt":datetime.now(timezone.utc).isoformat(),"status":"ok" if ranked else "error","count":len(ranked),"errors":errors,"highlights":ranked,"topKeywords":extract_keywords(ranked),"meta":{"llmEnabled":bool(os.getenv("LLM_API_URL")),"sources":["Hacker News","GitHub API","Reddit /r/programming"]}}
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} with {len(ranked)} items")


if __name__ == "__main__":
    main()
