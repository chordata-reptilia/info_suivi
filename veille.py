#!/usr/bin/env python3
"""
Veille RSS filtrée par mots-clés.

Lit plusieurs flux RSS, garde uniquement les articles dont le titre ou le
contenu contient un des mots-clés, fusionne le tout dans un flux RSS unique
(feed.xml) et notifie les NOUVEAUX articles sur Discord.

Conçu pour tourner en local (manuellement ou via cron). Idempotent : un
article déjà vu n'est ni redupliqué dans le flux ni renotifié.

Usage :
    python3 veille.py                 # exécution normale
    python3 veille.py --no-notify     # sans notification Discord (utile au 1er run)
    python3 veille.py --config x.yaml # autre fichier de config
"""

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
import yaml
from feedgen.feed import FeedGenerator

HERE = Path(__file__).resolve().parent


# ─────────────────────────── utilitaires texte ───────────────────────────

def normalize(text: str) -> str:
    """minuscule + suppression des accents, pour une comparaison robuste."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # uniformise les apostrophes typographiques ('/‘/’/`) en apostrophe droite
    text = re.sub(r"[‘’ʼ`]", "'", text)
    return text.lower()


def build_matchers(keywords):
    r"""
    Construit un (mot-clé, regex compilée) par mot-clé.

    - MAJUSCULES (PSE, PIP) -> mot entier exact : \bpse\b
    - sinon (grève, licenciement) -> racine + suffixe : \bgreve\w*
      (matche grève/grèves, licenciement/licenciements/licencié·es...)
    """
    matchers = []
    for kw in keywords:
        is_acronym = kw.isupper()
        norm = normalize(kw)
        # une espace dans le mot-clé -> on tolère espaces multiples
        core = r"\s+".join(re.escape(p) for p in norm.split())
        if is_acronym:
            pattern = r"\b" + core + r"\b"
        else:
            pattern = r"\b" + core + r"\w*"
        matchers.append((kw, re.compile(pattern)))
    return matchers


def matched_keywords(text, matchers):
    norm = normalize(text)
    return [kw for kw, rx in matchers if rx.search(norm)]


# ─────────────────────────── lecture des flux ───────────────────────────

def entry_id(entry):
    return entry.get("id") or entry.get("link") or entry.get("title", "")


def entry_datetime(entry):
    """datetime tz-aware (UTC) à partir du flux, ou maintenant en dernier recours."""
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            return datetime.fromtimestamp(time.mktime(st), tz=timezone.utc)
    return datetime.now(timezone.utc)


def entry_text(entry):
    """Concatène titre + résumé + contenu pour la recherche de mots-clés."""
    parts = [entry.get("title", ""), entry.get("summary", "")]
    for c in entry.get("content", []) or []:
        parts.append(c.get("value", ""))
    return "\n".join(parts)


def fetch_source(source, matchers):
    """Renvoie la liste des articles retenus pour une source."""
    url, name = source["url"], source["name"]
    try:
        parsed = feedparser.parse(url)
    except Exception as e:  # noqa: BLE001
        print(f"  [!] {name}: erreur de lecture ({e})", file=sys.stderr)
        return []
    if parsed.bozo and not parsed.entries:
        print(f"  [!] {name}: flux illisible ({parsed.get('bozo_exception')})",
              file=sys.stderr)
        return []

    kept = []
    for entry in parsed.entries:
        hits = matched_keywords(entry_text(entry), matchers)
        if not hits:
            continue
        kept.append({
            "id": entry_id(entry),
            "title": entry.get("title", "(sans titre)"),
            "link": entry.get("link", ""),
            "summary": re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()[:500],
            "source": name,
            "keywords": hits,
            "date": entry_datetime(entry).isoformat(),
        })
    print(f"  • {name}: {len(kept)} article(s) retenu(s) sur {len(parsed.entries)}")
    return kept


# ─────────────────────────── état (anti-doublon) ───────────────────────────

def load_store(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"  [!] {path.name} corrompu, réinitialisation.", file=sys.stderr)
    return {}


def save_store(path: Path, store: dict):
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2),
                    encoding="utf-8")


# ─────────────────────────── génération du flux ───────────────────────────

def write_feed(cfg, store: dict, out_path: Path):
    items = sorted(store.values(), key=lambda it: it["date"], reverse=True)
    items = items[: cfg.get("max_items", 150)]

    fg = FeedGenerator()
    fg.id(cfg["feed_link"])
    fg.title(cfg["feed_title"])
    fg.link(href=cfg["feed_link"], rel="alternate")
    fg.description(cfg["feed_description"])
    fg.language("fr")

    # feedgen exige l'ajout dans l'ordre chronologique inverse de l'affichage,
    # on ajoute donc du plus ancien au plus récent.
    for it in reversed(items):
        fe = fg.add_entry()
        fe.id(it["id"])
        fe.title(f"[{it['source']}] {it['title']}")
        if it["link"]:
            fe.link(href=it["link"])
        kw = ", ".join(it["keywords"])
        fe.description(f"<p><em>Mots-clés : {kw}</em></p>\n{it['summary']}")
        fe.pubDate(datetime.fromisoformat(it["date"]))
        fe.source(title=it["source"])

    fg.rss_file(str(out_path), pretty=True)
    print(f"  → flux écrit : {out_path}  ({len(items)} article(s))")


# ─────────────────────────── notifications Discord ───────────────────────────

def notify_discord(webhook: str, items):
    """Un message (embed) par nouvel article. Respecte une pause anti rate-limit."""
    sent = 0
    for it in items:
        embed = {
            "title": it["title"][:256],
            "url": it["link"] or None,
            "description": (it["summary"] or "")[:600],
            "color": 0xCC0000,
            "footer": {"text": f"{it['source']} · mots-clés : {', '.join(it['keywords'])}"},
            "timestamp": it["date"],
        }
        payload = {"embeds": [embed]}
        try:
            r = requests.post(webhook, json=payload, timeout=15)
            if r.status_code == 429:  # rate limited
                retry = r.json().get("retry_after", 2)
                time.sleep(float(retry) + 0.5)
                r = requests.post(webhook, json=payload, timeout=15)
            r.raise_for_status()
            sent += 1
            time.sleep(0.6)  # ménage le rate-limit Discord
        except Exception as e:  # noqa: BLE001
            print(f"  [!] Discord: échec pour « {it['title'][:40]} » ({e})",
                  file=sys.stderr)
    print(f"  → Discord : {sent}/{len(items)} notification(s) envoyée(s)")


# ─────────────────────────────────── main ───────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Veille RSS filtrée par mots-clés.")
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--no-notify", action="store_true",
                    help="ne pas envoyer de notification Discord")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    matchers = build_matchers(cfg["keywords"])
    store_path = HERE / cfg["state_file"]
    feed_path = HERE / cfg["output_feed"]

    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Veille — {len(cfg['sources'])} source(s)")
    store = load_store(store_path)
    first_run = not store

    # 1. récupération + filtrage
    found = []
    for src in cfg["sources"]:
        found.extend(fetch_source(src, matchers))

    # 2. détection des nouveautés
    new_items = [it for it in found if it["id"] not in store]
    for it in new_items:
        store[it["id"]] = it
    print(f"  {len(new_items)} nouvel(le)(s) article(s) depuis la dernière exécution.")

    # 3. (re)génération du flux agrégé
    write_feed(cfg, store, feed_path)

    # 4. notifications Discord (pas au tout premier run pour éviter le flood)
    webhook = None
    import os
    webhook = os.environ.get(cfg.get("discord_webhook_env", "DISCORD_WEBHOOK_URL"))
    if args.no_notify:
        print("  → notifications désactivées (--no-notify).")
    elif first_run:
        print("  → premier run : flux initialisé, pas de notification (anti-flood).")
    elif not webhook:
        print(f"  → pas de webhook ({cfg['discord_webhook_env']} non défini), "
              "notifications ignorées.")
    elif new_items:
        notify_discord(webhook, sorted(new_items, key=lambda it: it["date"]))

    # 5. sauvegarde de l'état
    save_store(store_path, store)
    print("  ✓ terminé.")


if __name__ == "__main__":
    main()
