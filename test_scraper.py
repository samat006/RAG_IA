"""
Scraper générique — fonctionne sur n'importe quel site web.
Changer de site = changer BASE_URL uniquement.

Lancer : python test_scraper.py
"""

import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import re
import time
import json

# ─────────────────────────────────────────────────────────────
# CONFIGURATION — seul endroit à modifier pour changer de site
# ─────────────────────────────────────────────────────────────
BASE_URL    = "https://tourisme-centrecorse.corsica"
DELAY       = 1.0    # secondes entre requêtes
MAX_PAGES   = 3      # pages testées par type de contenu
HEADERS     = {"User-Agent": "Mozilla/5.0 (compatible; RAG-bot/1.0; educational project)"}


# ─────────────────────────────────────────────────────────────
# 1. DÉCOUVERTE DES URLs (sitemap ou crawl de liens)
# ─────────────────────────────────────────────────────────────
def discover_urls(base_url: str, max_per_type: int = MAX_PAGES) -> dict:
    """
    Stratégie universelle :
    1. Cherche un sitemap XML (sitemap.xml ou sitemap_index.xml)
    2. Si absent → extrait les liens de la page d'accueil
    Retourne un dict { "type": [urls] }
    """
    urls = {}

    # Tentative sitemap XML
    for sitemap_path in ["/sitemap_index.xml", "/sitemap.xml"]:
        sitemap_url = base_url.rstrip("/") + sitemap_path
        found = _parse_sitemap(sitemap_url, max_per_type)
        if found:
            print(f"  ✅ Sitemap trouvé : {sitemap_url}")
            return found

    # Fallback : liens de la page d'accueil
    print("  ⚠️  Pas de sitemap — extraction des liens de la page d'accueil")
    resp = requests.get(base_url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(resp.text, "lxml")
    links = [
        a["href"] for a in soup.find_all("a", href=True)
        if a["href"].startswith(base_url) and a["href"] != base_url
    ]
    # Regrouper par "type" (segment d'URL)
    for link in links[:30]:
        path_parts = link.replace(base_url, "").strip("/").split("/")
        type_key = path_parts[0] if path_parts else "page"
        urls.setdefault(type_key, [])
        if len(urls[type_key]) < max_per_type and link not in urls[type_key]:
            urls[type_key].append(link)

    return urls


def _parse_sitemap(sitemap_url: str, max_per_type: int) -> dict:
    """Lit un sitemap XML et retourne des URLs par type."""
    try:
        resp = requests.get(sitemap_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception:
        return {}

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls_by_type = {}

    # Sitemap index (contient d'autres sitemaps)
    sub_sitemaps = root.findall(".//sm:sitemap/sm:loc", ns)
    if sub_sitemaps:
        print(f"  📋 {len(sub_sitemaps)} sous-sitemaps")
        for sm_loc in sub_sitemaps:
            sm_url = sm_loc.text
            # Nom du type depuis l'URL du sous-sitemap
            type_name = _url_to_type(sm_url)
            if type_name in urls_by_type:
                continue
            try:
                sm_resp = requests.get(sm_url, headers=HEADERS, timeout=10)
                sm_root = ET.fromstring(sm_resp.text)
                page_urls = [loc.text for loc in sm_root.findall(".//sm:loc", ns)]
                if page_urls:
                    urls_by_type[type_name] = page_urls[:max_per_type]
                    print(f"  📂 {type_name:20} : {len(page_urls):4} pages → {len(urls_by_type[type_name])} testées")
                time.sleep(DELAY * 0.5)
            except Exception as e:
                print(f"  ⚠️  {type_name} : {e}")
        return urls_by_type

    # Sitemap simple (liste directe d'URLs)
    page_locs = root.findall(".//sm:url/sm:loc", ns)
    if page_locs:
        for loc in page_locs[:max_per_type * 5]:
            url = loc.text
            type_name = _url_to_type(url)
            urls_by_type.setdefault(type_name, [])
            if len(urls_by_type[type_name]) < max_per_type:
                urls_by_type[type_name].append(url)
        return urls_by_type

    return {}


def _url_to_type(url: str) -> str:
    """Déduit un nom de type depuis le chemin d'une URL."""
    path = url.rstrip("/").split("/")[-1]          # dernier segment
    path = re.sub(r'[-_]\d+$', '', path)           # retirer suffixes numériques
    path = re.sub(r'sitemap[-_]?', '', path)       # retirer "sitemap"
    path = path.strip("-_").strip()
    return path[:30] if path else "page"


# ─────────────────────────────────────────────────────────────
# 2. EXTRACTION DE CONTENU (générique, tout site)
# ─────────────────────────────────────────────────────────────
def fetch_page(url: str) -> dict:
    """
    Extraction générique du contenu principal d'une page web.
    Fonctionne sans connaître la structure CSS du site.
    Stratégie : supprime les éléments parasites, prend le bloc avec le plus de texte.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"url": url, "error": str(e), "text": "", "title": "", "chars": 0}

    soup = BeautifulSoup(resp.text, "lxml")

    # Titre
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Métadonnées Schema.org (données structurées standard)
    structured = _extract_schema_org(soup)

    # Supprimer les éléments non-contenu
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "form", "noscript", "iframe", "svg",
                     "button", "input", "select", "textarea"]):
        tag.decompose()

    # Trouver le bloc de contenu principal par heuristique de densité
    main_text = _extract_main_content(soup)

    return {
        "url": url,
        "title": title,
        "text": main_text,
        "chars": len(main_text),
        "structured": structured,
    }


def _extract_main_content(soup: BeautifulSoup) -> str:
    """
    Heuristique universelle : prend le conteneur HTML
    qui a la plus grande densité texte/balises.
    Fonctionne sur WordPress, Drupal, sites custom, etc.
    """
    # Candidats par ordre de priorité sémantique
    candidates = [
        soup.find("main"),
        soup.find("article"),
        soup.find(id=re.compile(r"content|main|post|entry", re.I)),
        soup.find(class_=re.compile(r"content|main|post|entry|body", re.I)),
    ]
    candidates = [c for c in candidates if c is not None]

    if not candidates:
        candidates = [soup.find("body") or soup]

    # Choisir le candidat avec le plus de texte (densité)
    best = max(candidates, key=lambda tag: len(tag.get_text(strip=True)))

    lines = [l.strip() for l in best.get_text(separator="\n").splitlines() if l.strip()]
    # Dédoublonner les lignes consécutives identiques
    deduped = [lines[0]] if lines else []
    for line in lines[1:]:
        if line != deduped[-1]:
            deduped.append(line)

    return "\n".join(deduped)


def _extract_schema_org(soup: BeautifulSoup) -> dict:
    """
    Extrait les données structurées Schema.org (JSON-LD).
    Standard utilisé par la plupart des sites modernes —
    contient souvent nom, adresse, téléphone, horaires.
    """
    structured = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            # Peut être un objet ou une liste
            if isinstance(data, list):
                data = data[0] if data else {}
            structured.update({
                "nom":      data.get("name", ""),
                "adresse":  data.get("address", {}).get("streetAddress", "") if isinstance(data.get("address"), dict) else str(data.get("address", "")),
                "telephone":data.get("telephone", ""),
                "email":    data.get("email", ""),
                "type":     data.get("@type", ""),
                "description": data.get("description", ""),
            })
            # Retirer les champs vides
            structured = {k: v for k, v in structured.items() if v}
            break
        except (json.JSONDecodeError, AttributeError):
            continue

    # Fallback : balises <meta> og:title, og:description
    if not structured:
        for prop in ["og:title", "og:description", "og:url"]:
            tag = soup.find("meta", property=prop)
            if tag and tag.get("content"):
                key = prop.replace("og:", "")
                structured[key] = tag["content"]

    return structured


# ─────────────────────────────────────────────────────────────
# 3. MAIN — TEST
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print(f"  TEST SCRAPER GÉNÉRIQUE")
    print(f"  Site : {BASE_URL}")
    print("=" * 60)

    # ── Test 1 : page d'accueil ──────────────────────────────
    print("\n[TEST 1] Page d'accueil")
    home = fetch_page(BASE_URL)
    print(f"  Titre       : {home['title']}")
    print(f"  Texte       : {home['chars']} caractères")
    print(f"  Schema.org  : {home['structured']}")
    print(f"  Extrait     :\n{home['text'][:400]}")

    # ── Test 2 : découverte URLs ─────────────────────────────
    print("\n[TEST 2] Découverte des URLs")
    urls_by_type = discover_urls(BASE_URL, max_per_type=MAX_PAGES)
    total = sum(len(v) for v in urls_by_type.values())
    print(f"  {len(urls_by_type)} types trouvés, {total} URLs au total")

    # ── Test 3 : extraction de fiches ───────────────────────
    print("\n[TEST 3] Extraction de pages")
    results = []
    for type_name, urls in list(urls_by_type.items())[:5]:  # max 5 types
        for url in urls[:MAX_PAGES]:
            print(f"\n  [{type_name}] {url}")
            data = fetch_page(url)
            print(f"    Titre      : {data['title']}")
            print(f"    Chars      : {data['chars']}")
            print(f"    Schema.org : {data['structured']}")
            print(f"    Extrait    : {data['text'][:200]}")
            results.append(data)
            time.sleep(DELAY)

    # ── Résumé ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  RÉSUMÉ")
    print("=" * 60)
    ok = [r for r in results if not r.get("error") and r["chars"] > 0]
    ko = [r for r in results if r.get("error") or r["chars"] == 0]
    print(f"  Pages avec contenu  : {len(ok)}")
    print(f"  Pages vides/erreurs : {len(ko)}")
    if ok:
        avg = sum(r["chars"] for r in ok) // len(ok)
        print(f"  Taille moyenne      : {avg} caractères")
    with open("test_scraper_output.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n  💾 Résultats sauvegardés : test_scraper_output.json")


if __name__ == "__main__":
    main()
