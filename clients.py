"""
Configuration centralisée des clients.
Importé par server.py ET index_client.py sans dépendance circulaire.
"""

CLIENTS = {
    "sk-corte-tourisme-demo": {
        "name":       "Corte Tourisme",
        "corpus":     "./documents/corte-tourisme",
        "collection": "corpus_corte_tourisme",
        "web_sources": [
            "https://tourisme-centrecorse.corsica",
        ],
    },
    "sk-hotel-sampiero-2026": {
        "name":       "Hôtel Sampiero",
        "corpus":     "./documents/hotel-sampiero",
        "collection": "corpus_hotel_sampiero",
        "web_sources": [
            "http://www.sampierocorso.com/"
        ],
    },
}

LOCAL = {
    "corpus":     "./documents/test",
    "collection": "legal_corpus_m2_tp",
    "web_sources": [],
}
