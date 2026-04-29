import chromadb
from chromadb.config import Settings

# Modèles Ollama (local, 100% gratuit)
# Prérequis : ollama pull nomic-embed-text && ollama pull mistral
EMBED_MODEL = "nomic-embed-text"   # 768 dims, multilingue
GENERATION_MODEL = "mistral"        # 7B, bon sur le français

# Domaine du corpus
# Options : "legal", "municipal", "medical", "rh", "technique"
DOMAIN = "tourisme"

# PDF_MODE : stratégie d'extraction pour les PDFs non structurés
# "docling"    : IBM Docling, analyse layout par deep learning ← MEILLEUR POUR BROCHURES
#                (pip install docling, télécharge ~1-2GB de modèles au 1er run)
# "vision"     : Ollama LLaVA — lit la page comme un humain (ollama pull llava)
# "pdfplumber" : détection auto colonnes — correct pour la plupart des cas
# "markdown"   : pymupdf4llm → Markdown (limité sur layouts grille)
# "hybrid"     : PyMuPDF mots-XY + OCR par page au besoin
# "ocr"        : OCR Tesseract complet (PDFs scannés)
# "pymupdf"    : PyMuPDF texte brut (ancien comportement)
PDF_MODE = "docling"

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
