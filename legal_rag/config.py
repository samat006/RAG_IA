import chromadb
from chromadb.config import Settings

# Modèles Ollama (local, 100% gratuit)
# Prérequis : ollama pull nomic-embed-text && ollama pull mistral
EMBED_MODEL = "nomic-embed-text"   # 768 dims, multilingue
GENERATION_MODEL = "mistral"        # 7B, bon sur le français

# Domaine du corpus
# Options : "legal", "municipal", "medical", "rh", "technique"
DOMAIN = "municipal"

chroma_client = chromadb.PersistentClient(
    path="./chroma_legal_db",
    settings=Settings(
        anonymized_telemetry=False,
        allow_reset=True
    )
)

print("✅ Configuration chargée (Ollama local)")
