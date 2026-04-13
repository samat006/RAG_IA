import json
from typing import Dict, Any
from datetime import datetime
import ollama
from .config import GENERATION_MODEL

class LLMMetadataExtractor:
    """
    Extraction de métadonnées par LLM local (Ollama).

    Principe: On donne les 1500 premiers caractères du document au LLM
    et on lui demande d'extraire les métadonnées structurées en JSON.
    """

    @staticmethod
    def extract_legal_metadata(text: str, source_type: str = "pdf") -> Dict[str, Any]:
        """
        Extraction structurée de métadonnées par LLM.
        """
        print("  🤖 Extraction métadonnées par LLM...")

        prompt = f"""Tu es un expert en analyse de documents.
Voici le début d'un document. Extrait les métadonnées suivantes sous forme JSON stricte.

RÈGLES CRITIQUES:
- Si une information est absente, mets null (pas de chaîne vide)
- Les dates DOIVENT être en format ISO: YYYY-MM-DD
- Le dispositif doit être une valeur parmi: "Cassation", "Rejet", "Irrecevabilité", "Annulation", "Confirmation", "Infirmation", null
- La juridiction doit être normalisée: "Cour de cassation", "Cour d'appel", "Tribunal judiciaire", etc.
- N'invente AUCUNE information, sois factuel

Format JSON attendu:
{{
  "juridiction": "nom complet de la juridiction",
  "chambre": "ex: Chambre civile 2",
  "date_decision": "YYYY-MM-DD",
  "annee_decision": "YYYY",
  "numero_pourvoi": "ex: 89-61.265",
  "reference_complete": "ex: Cass. 2e civ., 12 oct. 1989, n° 89-61.265",
  "dispositif": "Cassation|Rejet|Irrecevabilité|...",
  "parties": ["Partie 1", "Partie 2"],
  "president": "nom du président si mentionné",
  "type_document": "arret|jugement|ordonnance"
}}

DOCUMENT:
{text[:1500]}

RÉPONDS UNIQUEMENT AVEC LE JSON, AUCUN TEXTE AVANT OU APRÈS."""

        try:
            response = ollama.chat(
                model=GENERATION_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"temperature": 0.0}
            )

            metadata_str = response.message.content
            metadata = json.loads(metadata_str)
            metadata = LLMMetadataExtractor._validate_metadata(metadata)

            print(f"  ✅ Métadonnées extraites: {metadata.get('reference_complete', 'N/A')}")
            return metadata

        except json.JSONDecodeError as e:
            print(f"  ⚠️ Erreur parsing JSON LLM: {e}")
            return {}

        except Exception as e:
            print(f"  ⚠️ Erreur extraction LLM: {e}")
            return {}

    @staticmethod
    def _validate_metadata(metadata: Dict) -> Dict:
        """
        Validation et normalisation des métadonnées extraites.
        """
        dispositif_mapping = {
            'cassation': 'Cassation',
            'rejet': 'Rejet',
            'irrecevabilité': 'Irrecevabilité',
            'irrecevabilite': 'Irrecevabilité',
            'annulation': 'Annulation',
            'confirmation': 'Confirmation',
            'infirmation': 'Infirmation'
        }

        if metadata.get('dispositif'):
            dispositif_lower = metadata['dispositif'].lower()
            metadata['dispositif'] = dispositif_mapping.get(
                dispositif_lower,
                metadata['dispositif']
            )

        if metadata.get('date_decision'):
            try:
                datetime.fromisoformat(metadata['date_decision'])
            except ValueError:
                print(f"  ⚠️ Date invalide: {metadata['date_decision']}")
                metadata['date_decision'] = None

        if not metadata.get('annee_decision') and metadata.get('date_decision'):
            metadata['annee_decision'] = metadata['date_decision'][:4]

        return metadata
