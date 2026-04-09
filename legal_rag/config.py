import os
from dotenv import load_dotenv
from mistralai import Mistral
import chromadb
from chromadb.config import Settings

# Configuration
load_dotenv()
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

if not MISTRAL_API_KEY:
    raise ValueError("MISTRAL_API_KEY non trouvée dans .env")

# Clients
mistral_client = Mistral(api_key=MISTRAL_API_KEY)

chroma_client = chromadb.PersistentClient(
    path="./chroma_legal_db",
    settings=Settings(
        anonymized_telemetry=False,
        allow_reset=True
    )
)

print("✅ Configuration chargée")
