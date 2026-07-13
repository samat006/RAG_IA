import os
import chromadb
from chromadb.config import Settings
from types import SimpleNamespace

# Embedding local (Ollama) — inchangé, pas de ré-indexation à froid possible
# sans casser l'espace vectoriel existant : non exposé dans le back-office.
EMBED_MODEL = "nomic-embed-text"

# Clé API Mistral — reste une variable d'environnement uniquement (jamais
# stockée en base ni éditable depuis /admin, pour ne pas garder un secret
# en clair dans un fichier SQLite non chiffré).
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")

# Domaine du corpus (personnalité de l'assistant) — fixe pour ce projet.
# Options possibles : "legal", "municipal", "medical", "rh", "technique", "tourisme"
DOMAIN = "tourisme"

# ── Réglages admin-éditables (back-office) ──────────────────────────────────
# `settings` est un objet MUTABLE partagé : tous les modules qui font
# `from .config import settings` reçoivent la MÊME instance, donc une
# mutation ultérieure d'un attribut (ex: settings.PDF_MODE = "hybrid")
# est visible partout sans réimport. C'est ce qui permet au back-office de
# changer ces réglages à chaud, sans redémarrer le serveur.
#
# Valeurs par défaut ci-dessous utilisées avant le premier appel à
# sync_from_store() (ex: scripts CLI qui n'utilisent pas store.py).
settings = SimpleNamespace(
    GENERATION_BACKEND="mistral_api",      # "mistral_api" | "ollama_local"
    GENERATION_MODEL="mistral-small-latest",
    PDF_MODE="docling",                    # docling|vision|pdfplumber|markdown|hybrid|ocr|pymupdf
    WEB_MODE="mixed",                      # "separate" | "mixed"
    MAX_DISTANCE=0.9,
    WEB_FALLBACK_THRESHOLD=0.6,
    N_RESULTS=12,
)


def sync_from_store():
    """Recharge `settings` depuis la base SQLite (store.py).
    Appelé au démarrage du serveur et après chaque sauvegarde dans /admin/settings."""
    from store import get_settings
    db = get_settings()
    settings.GENERATION_BACKEND = db["generation_backend"]
    settings.GENERATION_MODEL = db["generation_model"]
    settings.PDF_MODE = db["pdf_mode"]
    settings.WEB_MODE = db["web_mode"]
    settings.MAX_DISTANCE = db["max_distance"]
    settings.WEB_FALLBACK_THRESHOLD = db["web_fallback_threshold"]
    settings.N_RESULTS = db["n_results"]


# ── Sources web ────────────────────────────────────────────────
# Vestige : utilisé uniquement en fallback par main.py (CLI de test), quand
# aucune liste explicite de web_sources n'est fournie. Le serveur Flask et
# index_client.py passent toujours une liste explicite (store.list_url_strings).
WEB_SOURCES = [
    "https://tourisme-centrecorse.corsica",
]

# Nombre max de pages à scraper par site. None = pas de limite.
WEB_MAX_PAGES = 3

# URLs à exclure de l'indexation web (correspondance par sous-chaîne).
# Exemples :
#   "/contact"        → exclut toutes les pages dont l'URL contient "/contact"
#   "/mentions-legales" → exclut cette page précise
#   "?page="          → exclut les pages de pagination
WEB_EXCLUDED_URLS: list = [
    "/transport",
     "/tag",
     "/type",
     "/category",
     "/classification",
]

# Nombre max de sources (URLs) renvoyées au client avec la réponse.
SOURCES_MAX_COUNT = 3

# Taille max d'un chunk en caractères (utilisé par chunkers + indexer)
MAX_CHUNK_SIZE = 2000

# Rétrocompatibilité
USE_OCR = False

chroma_client = chromadb.PersistentClient(
    path="./chroma_legal_db",
    settings=Settings(
        anonymized_telemetry=False,
        allow_reset=True
    )
)

print("✅ Configuration chargée (Ollama local)")
