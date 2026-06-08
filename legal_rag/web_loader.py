"""
WebLoader générique — scrape n'importe quel site web.
Changer de site = changer WEB_SOURCES dans config.py uniquement.
Produit le même format de sortie que PDFLoader.
"""

import re
import time
import json
import uuid
import xml.etree.ElementTree as ET
from typing import Dict, Any, List

import requests
from bs4 import BeautifulSoup

from .config import DOMAIN, WEB_EXCLUDED_URLS
from .models import DocumentMetadata

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RAG-bot/1.0; educational project)"}
DELAY   = 1.0   # secondes entre requêtes


class WebLoader:
    """
    Scrape un site web et produit des chunks prêts à indexer.
    Fonctionne sur tout site avec un sitemap XML ou une page d'accueil.
    """

    def __init__(self, base_url: str, max_pages: int = 200, delay: float = DELAY):
        self.base_url  = base_url.rstrip("/")
        self.max_pages = max_pages
        self.delay     = delay

    # ─────────────────────────────────────────────────────────────
    # POINT D'ENTRÉE
    # ─────────────────────────────────────────────────────────────
    def load_all(self) -> List[Dict[str, Any]]:
        """
        Découvre les URLs du site et retourne une liste de documents
        au format {'raw_text': ..., 'metadata': DocumentMetadata}.
        """
        print(f"\n🌐 WebLoader : {self.base_url}")
        urls = self._discover_urls()
        print(f"  {len(urls)} URLs découvertes")

        pages = urls if self.max_pages is None else urls[:self.max_pages]
        total = len(pages)
        documents = []
        for i, url in enumerate(pages, 1):
            print(f"  [{i}/{total}] {url}")
            doc = self._load_page(url)
            if doc and doc["raw_text"].strip():
                documents.append(doc)
            time.sleep(self.delay)

        print(f"  ✅ {len(documents)} pages chargées")
        return documents

    # ─────────────────────────────────────────────────────────────
    # DÉCOUVERTE DES URLs (sitemap ou liens de la page d'accueil)
    # ─────────────────────────────────────────────────────────────
    def _is_excluded(self, url: str) -> bool:
        return any(pattern in url for pattern in WEB_EXCLUDED_URLS if pattern)

    def _discover_urls(self) -> List[str]:
        for path in ["/sitemap_index.xml", "/sitemap.xml"]:
            urls = self._parse_sitemap(self.base_url + path)
            if urls:
                urls = [u for u in urls if not self._is_excluded(u)]
                return urls
        urls = self._crawl_homepage()
        return [u for u in urls if not self._is_excluded(u)]

    def _parse_sitemap(self, sitemap_url: str) -> List[str]:
        try:
            resp = requests.get(sitemap_url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except Exception:
            return []

        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls: List[str] = []

        # Sitemap index → récursion sur sous-sitemaps
        for sm_loc in root.findall(".//sm:sitemap/sm:loc", ns):
            try:
                sub = requests.get(sm_loc.text, headers=HEADERS, timeout=10)
                sub_root = ET.fromstring(sub.text)
                urls += [loc.text for loc in sub_root.findall(".//sm:loc", ns)]
                time.sleep(self.delay * 0.3)
            except Exception:
                pass

        # Sitemap simple
        if not urls:
            urls = [loc.text for loc in root.findall(".//sm:url/sm:loc", ns)]

        # Filtrer les URLs du même domaine et exclure les fichiers non-HTML
        urls = [
            u for u in urls
            if u.startswith(self.base_url)
            and not re.search(r'\.(xml|pdf|jpg|jpeg|png|gif|css|js)$', u, re.I)
        ]
        return list(dict.fromkeys(urls))  # dédoublonner tout en gardant l'ordre

    def _crawl_homepage(self) -> List[str]:
        """Fallback si pas de sitemap : extrait les liens internes de la page d'accueil."""
        try:
            resp = requests.get(self.base_url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(resp.text, "lxml")
            links = [
                a["href"] for a in soup.find_all("a", href=True)
                if a["href"].startswith(self.base_url) and a["href"] != self.base_url
                and not re.search(r'\.(pdf|jpg|png|gif|css|js)$', a["href"], re.I)
            ]
            return list(dict.fromkeys(links))
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────────
    # CHARGEMENT D'UNE PAGE
    # ─────────────────────────────────────────────────────────────
    def _load_page(self, url: str) -> Dict[str, Any]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            print(f"    ⚠️ Erreur : {e}")
            return {}

        soup = BeautifulSoup(resp.text, "lxml")

        title = soup.find("title")
        title = title.get_text(strip=True) if title else url

        structured = self._extract_schema_org(soup)

        # Supprimer le bruit
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "noscript", "iframe", "svg",
                         "button", "input", "select"]):
            tag.decompose()

        text = self._extract_main_content(soup)

        # Ajouter les données structurées au texte pour améliorer le retrieval
        if structured:
            extras = "\n".join(f"{k}: {v}" for k, v in structured.items() if v)
            text = extras + "\n\n" + text if extras else text

        if len(text.strip()) < 30:
            return {}

        metadata = DocumentMetadata(
            document_id=f"web_{uuid.uuid4().hex[:8]}",
            source_file=url,
            source_type="web",
            domain=DOMAIN,
            objet=title,
            contact=structured.get("telephone", "") or structured.get("email", ""),
        )

        return {"raw_text": text, "metadata": metadata}

    # ─────────────────────────────────────────────────────────────
    # EXTRACTION DE CONTENU (heuristique universelle)
    # ─────────────────────────────────────────────────────────────
    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        candidates = [
            soup.find("main"),
            soup.find("article"),
            soup.find(id=re.compile(r"content|main|post|entry", re.I)),
            soup.find(class_=re.compile(r"content|main|post|entry|body", re.I)),
            soup.find("body"),
        ]
        best = next((c for c in candidates if c), soup)

        lines = [l.strip() for l in best.get_text(separator="\n").splitlines() if l.strip()]
        deduped = [lines[0]] if lines else []
        for line in lines[1:]:
            if line != deduped[-1]:
                deduped.append(line)
        return "\n".join(deduped)

    def _extract_schema_org(self, soup: BeautifulSoup) -> dict:
        """Extrait les données structurées JSON-LD (standard moderne)."""
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, list):
                    data = data[0] if data else {}
                result = {
                    "nom":       data.get("name", ""),
                    "adresse":   data.get("address", {}).get("streetAddress", "")
                                 if isinstance(data.get("address"), dict)
                                 else str(data.get("address", "")),
                    "telephone": data.get("telephone", ""),
                    "email":     data.get("email", ""),
                    "description": data.get("description", ""),
                }
                return {k: v for k, v in result.items() if v}
            except Exception:
                continue
        return {}
