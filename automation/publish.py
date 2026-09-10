#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish.py - motore unico per pubblicare ARTICOLI e PRODOTTI (Jekyll/GitHub Pages).
Uso da riga di comando o import. Fa slug, file .md, git add/commit/push automatico.
Repo e URL sito sono in automation/config.json — cambia progetto senza toccare questo file.

USO ARTICOLO:
    python publish.py articolo "Titolo Articolo" "categoria" "Excerpt breve." "Corpo markdown..."

USO PRODOTTO:
    python publish.py prodotto "Nome Prodotto" prezzo "categoria" "sku" "descrizione breve" "Corpo markdown..." [image_url]

Oppure importa le funzioni pubblica_articolo() / pubblica_prodotto() da un altro script.
"""
import sys
import os
import re
import json
import time
import subprocess
import unicodedata
import urllib.request
import urllib.error
from datetime import date, datetime

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
    _cfg = json.load(_f)

REPO = _cfg["repo"]  # root del progetto — modificare in automation/config.json, non qui
SITE_BASE = _cfg["site_base"]  # modificare in automation/config.json, non qui
LOG_PATH = os.path.join(REPO, "automation", "publish_log.jsonl")


class PublishError(Exception):
    """Errore di validazione o pubblicazione — blocca prima di scrivere/pushare."""
    pass


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-+", "-", text)
    return text


def _check_yaml_safe(*values):
    """Blocca caratteri che rompono il parser YAML/Jekyll (lezione da cmspush)."""
    pericolosi = ["&", "?", "[", "]", "{", "}", "\n"]
    for v in values:
        if v is None:
            continue
        for ch in pericolosi:
            if ch in str(v):
                raise PublishError(
                    f"Carattere '{ch}' non ammesso in un campo YAML (trovato in: {v!r}). "
                    f"Riscrivere il testo senza quel simbolo prima di pubblicare."
                )


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _check_categoria_articolo(categoria):
    path = os.path.join(REPO, "_data", "categorie.json")
    cats = [c["nome"] for c in _load_json(path)]
    if categoria not in cats:
        raise PublishError(
            f"Categoria articolo '{categoria}' non esiste in _data/categorie.json. "
            f"Categorie valide: {cats}. Chiedere a Mirco prima di crearne una nuova."
        )


def _check_categoria_prodotto(categoria):
    path = os.path.join(REPO, "_data", "shop-categorie.json")
    cats = [c["nome"] for c in _load_json(path)]
    if categoria not in cats:
        raise PublishError(
            f"Categoria prodotto '{categoria}' non esiste in _data/shop-categorie.json. "
            f"Categorie valide: {cats}. Chiedere a Mirco prima di crearne una nuova."
        )


def _check_no_duplicate(fpath):
    if os.path.exists(fpath):
        raise PublishError(
            f"Esiste gia' un file con lo stesso slug: {fpath}. "
            f"Scegliere un titolo/nome diverso o usare la funzione di aggiornamento (non ancora implementata)."
        )


def _log(kind, titolo, slug, url, fname):
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "tipo": kind,
        "titolo": titolo,
        "slug": slug,
        "file": fname,
        "url": url,
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _scarica_immagine_locale(url, sottocartella, slug):
    """Scarica un'immagine da URL esterno e la salva dentro il repo (assets/images/{sottocartella}/),
    cosi' non dipende piu' da un servizio esterno (Wikimedia, hotlink, rate-limit, URL che cambia, ecc.).
    Ritorna il path relativo Jekyll da usare nel front-matter (es. /assets/images/posts/slug.jpg),
    o solleva PublishError se il download fallisce (status non 200, o content-type non e' un'immagine)."""
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"  # fallback ragionevole
    fname = f"{slug}{ext}"
    dir_path = os.path.join(REPO, "assets", "images", sottocartella)
    os.makedirs(dir_path, exist_ok=True)
    fpath = os.path.join(dir_path, fname)

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                raise PublishError(f"Download immagine fallito: HTTP {resp.status} da {url}")
            content_type = resp.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                raise PublishError(f"URL immagine non restituisce un'immagine (Content-Type: {content_type}) -> {url}")
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise PublishError(f"Download immagine fallito: HTTP {e.code} da {url}")
    except urllib.error.URLError as e:
        raise PublishError(f"Download immagine fallito: {e.reason} da {url}")

    with open(fpath, "wb") as f:
        f.write(data)

    print(f"Immagine scaricata e salvata nel repo: assets/images/{sottocartella}/{fname} ({len(data)} bytes)")
    return f"{SITE_BASE}/assets/images/{sottocartella}/{fname}"


def _git_push(msg):
    subprocess.run(["git", "add", "."], cwd=REPO, check=True)
    r = subprocess.run(["git", "commit", "-m", msg], cwd=REPO, capture_output=True, text=True)
    # se non c'e' nulla da committare, non e' un errore
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
        print("COMMIT WARNING:", r.stdout, r.stderr)
    push = subprocess.run(["git", "push"], cwd=REPO, capture_output=True, text=True)
    if push.returncode != 0:
        # fetch first -> pull --rebase e riprova
        subprocess.run(["git", "pull", "--rebase"], cwd=REPO, check=True)
        r2 = subprocess.run(["git", "push"], cwd=REPO, capture_output=True, text=True)
        if r2.returncode != 0:
            raise PublishError(f"git push fallito anche dopo pull --rebase: {r2.stdout} {r2.stderr}")


def verifica_live(url, tentativi=18, intervallo=10):
    """Polling reale sull'URL pubblico finche' non risponde 200 (o scade il timeout).
    GitHub Pages impiega di solito 30-90s per il build dopo un push."""
    print(f"Verifica deploy in corso su {url} ...")
    time.sleep(8)  # margine iniziale, il build non parte istantaneamente
    for i in range(1, tentativi + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    print(f"OK LIVE (200) dopo {8 + (i-1)*intervallo}s -> {url}")
                    return True
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"HTTP {e.code} al tentativo {i}, ritento...")
        except Exception as e:
            print(f"Errore rete al tentativo {i}: {e}, ritento...")
        time.sleep(intervallo)
    print(f"ATTENZIONE: {url} non ha ancora risposto 200 dopo {8 + tentativi*intervallo}s. "
          f"Puo' essere solo lentezza del build — ricontrollare manualmente tra poco.")
    return False


def pubblica_articolo(titolo, categoria, excerpt, corpo, data=None, verifica=True, image=None, image_caption=None):
    """Crea _posts/YYYY-MM-DD-slug.md con front-matter pulito, fa commit+push.
    Valida categoria, caratteri YAML, duplicati. Verifica live (200) dopo il push se verifica=True.
    image: URL opzionale, mostrato come hero image in cima all'articolo (page.header.image, gia' supportato da _layouts/single.html).
    image_caption: didascalia opzionale sotto l'immagine hero."""
    _check_yaml_safe(titolo, categoria, excerpt, image_caption)
    _check_categoria_articolo(categoria)

    d = data or date.today().isoformat()
    slug = slugify(titolo)
    fname = f"{d}-{slug}.md"
    fpath = os.path.join(REPO, "_posts", fname)
    _check_no_duplicate(fpath)

    if image and image.startswith("http"):
        image = _scarica_immagine_locale(image, "posts", slug)

    fm = (
        "---\n"
        "layout: single\n"
        f'title: "{titolo}"\n'
        f"date: {d}\n"
        f'excerpt: "{excerpt}"\n'
        "categories:\n"
        f"  - {categoria}\n"
    )
    if image:
        fm += "header:\n"
        fm += f'  image: "{image}"\n'
        fm += f'  teaser: "{image}"\n'
        if image_caption:
            fm += f'  caption: "{image_caption}"\n'
    fm += "---\n\n"
    with open(fpath, "w", encoding="utf-8", newline="\n") as f:
        f.write(fm + corpo.strip() + "\n")

    _git_push(f"Nuovo articolo: {titolo}")
    url = f"{SITE_BASE}/{categoria}/{slug}/"
    _log("articolo", titolo, slug, url, fname)
    print(f"OK ARTICOLO -> {fname}")
    print(f"URL -> {url}")
    if verifica:
        verifica_live(url)
    return fname


def pubblica_prodotto(nome, prezzo, categoria, sku, descrizione, corpo,
                       image=None, stock=20, badge=None, price_original=None,
                       colors=None, sizes=None, shipping=None, verifica=True,
                       tipo="fisico"):
    """Crea _products/slug.md con front-matter pulito, fa commit+push.
    Valida categoria, caratteri YAML, duplicati. Verifica live (200) dopo il push se verifica=True.
    tipo: "fisico" (default, richiede indirizzo spedizione al checkout) o "digitale"
    (richiede solo email al checkout, nessun indirizzo/corriere)."""
    if tipo not in ("fisico", "digitale"):
        raise PublishError(f"tipo deve essere 'fisico' o 'digitale', ricevuto: {tipo!r}")
    _check_yaml_safe(nome, categoria, sku, descrizione, badge, colors, sizes, shipping)
    _check_categoria_prodotto(categoria)

    slug = slugify(nome)
    fname = f"{slug}.md"
    fpath = os.path.join(REPO, "_products", fname)
    _check_no_duplicate(fpath)

    if image and image.startswith("http"):
        image = _scarica_immagine_locale(image, "products", slug)

    lines = [
        "---",
        f'title: "{nome}"',
        f"price: {prezzo}",
    ]
    if price_original:
        lines.append(f"price_original: {price_original}")
    lines.append(f"stock: {stock}")
    lines.append(f'sku: "{sku}"')
    lines.append(f'category: "{categoria}"')
    lines.append(f'tipo: "{tipo}"')
    if badge:
        lines.append(f'badge: "{badge}"')
    if colors:
        lines.append(f'colors: "{colors}"')
    if sizes:
        lines.append(f'sizes: "{sizes}"')
    if shipping:
        lines.append(f'shipping: "{shipping}"')
    if image:
        lines.append(f'image: "{image}"')
    lines.append(f'description: "{descrizione}"')
    lines.append("layout: product")
    lines.append("---")
    fm = "\n".join(lines) + "\n\n"

    with open(fpath, "w", encoding="utf-8", newline="\n") as f:
        f.write(fm + corpo.strip() + "\n")

    _git_push(f"Nuovo prodotto: {nome}")
    url = f"{SITE_BASE}/shop/{slug}/"
    _log("prodotto", nome, slug, url, fname)
    print(f"OK PRODOTTO -> {fname}")
    print(f"URL -> {url}")
    if verifica:
        verifica_live(url)
    return fname


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    kind = args[0]
    if kind == "articolo":
        _, titolo, categoria, excerpt, corpo = args
        pubblica_articolo(titolo, categoria, excerpt, corpo)
    elif kind == "prodotto":
        _, nome, prezzo, categoria, sku, descrizione, corpo, *rest = args
        image = rest[0] if rest else None
        pubblica_prodotto(nome, prezzo, categoria, sku, descrizione, corpo, image=image)
    else:
        print("Primo argomento deve essere 'articolo' o 'prodotto'")
        sys.exit(1)