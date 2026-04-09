from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
import json

@dataclass
class LegalDocumentMetadata:
    """
    Classe de métadonnées pour documents juridiques.
    """
    # Identification
    document_id: str
    source_file: str
    source_type: str
    
    # Juridiques
    juridiction: Optional[str] = None
    chambre: Optional[str] = None
    date_decision: Optional[str] = None
    annee_decision: Optional[str] = None
    numero_pourvoi: Optional[str] = None
    reference_complete: Optional[str] = None
    dispositif: Optional[str] = None
    type_document: Optional[str] = None
    parties: Optional[List[str]] = field(default_factory=list)
    president: Optional[str] = None
    
    # Ingestion
    date_ingestion: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_chromadb_metadata(self) -> Dict[str, str]:
        """
        Conversion pour ChromaDB (uniquement types simples).
        """
        meta = {}
        for key, value in self.__dict__.items():
            if value is not None:
                if isinstance(value, list):
                    # ChromaDB n'accepte pas les listes directement
                    meta[key] = json.dumps(value, ensure_ascii=False)
                else:
                    meta[key] = str(value)
        return meta
