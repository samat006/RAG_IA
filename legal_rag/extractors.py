import json
from typing import Dict, Any
from datetime import datetime
from .config import mistral_client

class LLMMetadataExtractor:
    """
    Extraction de métadonnées juridiques par LLM.
    
    Principe: On donne les 1500 premiers caractères du document au LLM
    et on lui demande d'extraire les métadonnées structurées.
    """
    
    @staticmethod
    def extract_legal_metadata(text: str, source_type: str = "pdf") -> Dict[str, Any]:
        """
        Extraction structurée de métadonnées par LLM.
        """
        print("  🤖 Extraction métadonnées par LLM...")
        
        # Prompt adapté aux documents juridiques français
        prompt = f"""Tu es un expert en analyse de documents juridiques français.

Voici le début d'un document juridique (arrêt, jugement, ou ordonnance).
Extrait les métadonnées suivantes sous forme JSON stricte.

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
            # Appel Mistral avec mode JSON forcé
            response = mistral_client.chat.complete(
                model="mistral-small-latest",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0  # Déterministe pour extraction
            )
            
            # Parsing de la réponse
            metadata_str = response.choices[0].message.content
            metadata = json.loads(metadata_str)
            
            # Validation et nettoyage
            metadata = LLMMetadataExtractor._validate_metadata(metadata)
            
            print(f"  ✅ Métadonnées extraites: {metadata.get('reference_complete', 'N/A')}")
            
            return metadata
        
        except json.JSONDecodeError as e:
            print(f"  ⚠️ Erreur parsing JSON LLM: {e}")
            print(f"  Réponse brute: {metadata_str[:200]}")
            return {}
        
        except Exception as e:
            print(f"  ⚠️ Erreur extraction LLM: {e}")
            return {}
    
    @staticmethod
    def _validate_metadata(metadata: Dict) -> Dict:
        """
        Validation et normalisation des métadonnées extraites.
        """
        # Normalisation du dispositif (vocabulaire contrôlé)
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
        
        # Validation de la date (format ISO)
        if metadata.get('date_decision'):
            try:
                datetime.fromisoformat(metadata['date_decision'])
            except ValueError:
                print(f"  ⚠️ Date invalide: {metadata['date_decision']}")
                metadata['date_decision'] = None
        
        # Extraction de l'année si pas fournie
        if not metadata.get('annee_decision') and metadata.get('date_decision'):
            metadata['annee_decision'] = metadata['date_decision'][:4]
        
        return metadata
