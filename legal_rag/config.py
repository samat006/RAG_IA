import os
import chromadb
from chromadb.config import Settings

# Modèles Ollama (local, 100% gratuit)
# Prérequis : ollama pull nomic-embed-text && ollama pull phi3
EMBED_MODEL = "nomic-embed-text"   # 768 dims, multilingue
GENERATION_MODEL = os.environ.get("GENERATION_MODEL", "mistral")

# Domaine du corpus
# Options : "legal", "municipal", "medical", "rh", "technique"
DOMAIN = "tourisme"

# PDF_MODE : stratégie d'extraction pour les PDFs non structurés
# "docling"    : IBM Docling, analyse layout par deep learning ← MEILLEUR POUR BROCHURES
# "vision"     : Ollama LLaVA (ollama pull llava)
# "pdfplumber" : détection auto colonnes
# "markdown"   : pymupdf4llm → Markdown
# "hybrid"     : PyMuPDF + OCR par page
# "ocr"        : OCR Tesseract complet
# "pymupdf"    : PyMuPDF texte brut
PDF_MODE = "docling"

# ── Sources web ────────────────────────────────────────────────
# Liste des sites à indexer. Ajouter autant d'URLs que nécessaire.
# Mettre [] pour désactiver la recherche web.
WEB_SOURCES = [
    "https://tourisme-centrecorse.corsica",
    # "https://autre-site.com",
]

# Nombre max de pages à scraper par site. None = pas de limite.
WEB_MAX_PAGES = None

# WEB_MODE : comportement quand documents ET web sont disponibles
# "separate" : cherche d'abord dans les documents locaux ;
#              si rien de pertinent → cherche sur le web.
#              Cite toujours la source. Refuse de répondre sans source.
# "mixed"    : fusionne les résultats documents + web avant de répondre.
WEB_MODE = "mixed"

# Seuil de distance en dessous duquel on considère qu'un document répond
# (mode "separate"). Si tous les résultats sont au-dessus → bascule sur le web.
WEB_FALLBACK_THRESHOLD = 0.6

# Seuil max de distance L2 pour les chunks envoyés au LLM.
# 0=identique, 1.41=orthogonal — au-dessus, le chunk est ignoré.
MAX_DISTANCE = 1.5

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
