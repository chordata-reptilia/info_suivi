#!/usr/bin/env python3
"""
Détecteur de flux RSS/Atom.

Pour chaque URL donnée, essaie l'URL elle-même puis des chemins courants
(/feed/, /rss, /feeds/posts/default..., feed.xml...) et lit aussi le <head>
HTML à la recherche d'un <link rel="alternate" type="application/rss+xml">.

Usage :
    python3 detect_feed.py https://site1.org https://site2.org ...
"""

import re
import sys
from urllib.parse import urljoin

import feedparser
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/rss+xml,application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
}

CANDIDATE_PATHS = [
    "",                              # l'URL telle quelle
    "feed/", "feed", "rss/", "rss", "rss.xml", "feed.xml",
    "atom.xml", "index.xml",
    "feeds/posts/default?alt=rss",  # Blogspot
    "?feed=rss2",                   # WordPress fallback
]


def try_feed(url):
    """Renvoie (titre, nb_items) si url est un vrai flux, sinon None."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception:
        return None
    parsed = feedparser.parse(r.content)
    if parsed.entries and parsed.feed.get("title"):
        return parsed.feed.get("title", "?"), len(parsed.entries)
    return None


def find_in_html(base_url):
    """Cherche une balise <link rel=alternate type=...rss/atom...> dans la page."""
    try:
        r = requests.get(base_url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception:
        return None
    html = r.text
    for m in re.finditer(r"<link[^>]+>", html, re.I):
        tag = m.group(0)
        if re.search(r'type=["\']application/(rss|atom)\+xml', tag, re.I):
            href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
            if href:
                return urljoin(base_url, href.group(1))
    return None


def detect(url):
    base = url if url.endswith("/") else url + "/"
    # 1) chemins candidats
    for path in CANDIDATE_PATHS:
        candidate = url if path == "" else urljoin(base, path)
        res = try_feed(candidate)
        if res:
            return candidate, res
    # 2) déclaration dans le HTML
    declared = find_in_html(url)
    if declared:
        res = try_feed(declared)
        if res:
            return declared, res
    return None, None


def main():
    urls = sys.argv[1:]
    if not urls:
        print("Usage: python3 detect_feed.py <url> [url ...]")
        return
    for url in urls:
        feed_url, info = detect(url)
        if feed_url:
            title, n = info
            print(f"[OK ] {url}\n       -> {feed_url}\n       ({n} articles — « {title} »)")
        else:
            print(f"[KO ] {url}\n       -> aucun flux trouvé")
        print()


if __name__ == "__main__":
    main()
