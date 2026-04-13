from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
import json

@dataclass
class DocumentMetadata:
    """
    Métadonnées génériques pour tout type de document.
    Couvre : juridique, municipal, RH, médical, technique, etc.
    """
    # ── Identification ──────────────────────────────────────────
    document_id: str
    source_file: str
    source_type: str          # pdf, xml, json
    domain: str = "municipal" # legal, municipal, medical, rh, technique

    # ── Champs communs (tous domaines) ──────────────────────────
    type_document: Optional[str] = None      # délibération, arrêté, jugement, contrat…
    date_decision: Optional[str] = None      # ISO YYYY-MM-DD
    annee_decision: Optional[str] = None
    reference_complete: Optional[str] = None # référence lisible complète
    objet: Optional[str] = None              # sujet / titre du document

    # ── Champs municipal ────────────────────────────────────────
    collectivite: Optional[str] = None       # "Mairie de Paris", "Commune de Lyon"
    numero_deliberation: Optional[str] = None
    rapporteur: Optional[str] = None
    vote_resultat: Optional[str] = None      # "Adopté", "Rejeté", "Ajourné"
    service_emetteur: Optional[str] = None   # "Direction des travaux", "DRH"…
    seance_date: Optional[str] = None        # date de la séance du conseil

    # ── Champs juridique (rétrocompatibilité) ───────────────────
    juridiction: Optional[str] = None
    chambre: Optional[str] = None
    numero_pourvoi: Optional[str] = None
    dispositif: Optional[str] = None
    parties: Optional[List[str]] = field(default_factory=list)
    president: Optional[str] = None

    # ── Ingestion ───────────────────────────────────────────────
    date_ingestion: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_chromadb_metadata(self) -> Dict[str, str]:
        """Conversion pour ChromaDB (types simples uniquement)."""
        meta = {}
        for key, value in self.__dict__.items():
            if value is not None:
                if isinstance(value, list):
                    meta[key] = json.dumps(value, ensure_ascii=False)
                else:
                    meta[key] = str(value)
        return meta


# Alias rétrocompatibilité (ancien nom utilisé dans les imports)
LegalDocumentMetadata = DocumentMetadata
