"""
État partagé du serveur : pipelines par client + générateur de réponses,
et la logique pour les (re)construire.

Ce module existe séparément de server.py pour une raison précise : server.py
est lancé via `python server.py`, ce qui l'exécute comme `__main__` — PAS
comme un module nommé `server`. Si admin_routes.py faisait `import server`,
Python ne trouverait aucun module `server` déjà chargé dans sys.modules (seul
`__main__` y est), et réexécuterait donc server.py *depuis zéro* sous ce nom,
créant un second `PIPELINES` totalement déconnecté de celui utilisé par les
routes réellement servies (bug constaté : un client fraîchement créé restait
introuvable de /ask, qui lisait le PIPELINES de l'exécution `__main__`,
alors que sa pipeline avait été enregistrée dans le PIPELINES du re-import
fantôme). server.py et admin_routes.py importent donc tous les deux CE
module normalement (au niveau du fichier, pas en différé) : aucun des deux
n'a besoin de connaître l'identité de l'autre.
"""
import threading

from legal_rag.pipeline import IngestionPipeline
from legal_rag.generation import AnswerGenerator
import store

PIPELINES: dict = {}
generator: "AnswerGenerator | None" = None

# Port sur lequel /admin/* doit être servi (voir server.py, bloc __main__).
# admin_routes.py refuse toute requête /admin/* arrivée sur un autre port —
# défense en profondeur en plus du binding 127.0.0.1 du port admin lui-même.
ADMIN_PORT: int = 5001


def register_client_pipeline(cfg: dict) -> IngestionPipeline:
    """
    Construit le pipeline d'un client et l'enregistre dans PIPELINES.
    Appelé au démarrage pour chaque client existant, et de façon SYNCHRONE lors
    de la création d'un nouveau client depuis le back-office (corpus vide au
    départ, donc rapide) — pour ne jamais laisser /ask retomber silencieusement
    sur le pipeline local le temps qu'un pipeline soit prêt (fuite inter-client).
    """
    p = IngestionPipeline(collection_name=cfg["collection"], retriever_type="recursive")
    p.ingest_corpus(cfg["corpus_dir"], web_sources=store.list_url_strings(cfg["key"]))
    PIPELINES[cfg["key"]] = p
    return p


def trigger_reindex(client_key: str, mode: str = "both", reset: bool = True):
    """Ré-indexation en tâche de fond — réutilisée par /admin/index/<key> (legacy,
    protégé par token, pour usage CLI/API) et par le bouton "Réindexer" du
    back-office (protégé par session admin)."""
    cfg = store.get_client(client_key)
    if cfg is None:
        raise ValueError("Client inconnu")

    def run():
        p = IngestionPipeline(collection_name=cfg["collection"], retriever_type="recursive")
        p.ingest_corpus(cfg["corpus_dir"], force=reset,
                         web_sources=store.list_url_strings(client_key), mode=mode)
        PIPELINES[client_key] = p
        print(f"✅ Re-indexation terminée : {cfg['name']} ({mode})")

    threading.Thread(target=run, daemon=True).start()


def init_pipelines():
    """Construit les pipelines de tous les clients existants au démarrage du serveur."""
    for cfg in store.list_clients():
        try:
            register_client_pipeline(cfg)
            print(f"✅ Pipeline chargé : {cfg['name']}")
        except Exception as e:
            print(f"⚠️  Échec chargement pipeline {cfg['name']} : {e}")


def reload_generator():
    """(Re)construit le générateur global — au démarrage, et après un changement
    dans /admin/settings."""
    global generator
    generator = AnswerGenerator()
    print(f"🤖 Backend : {generator.backend} | Modèle : {generator.model}")
