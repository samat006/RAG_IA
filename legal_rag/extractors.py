import json
from typing import Dict, Any
from datetime import datetime
import ollama
from .config import GENERATION_MODEL, DOMAIN

# ── Prompts d'extraction par domaine ────────────────────────────────────────
EXTRACTION_PROMPTS = {
    "legal": {
        "context": "expert en analyse de documents juridiques français",
        "fields": """{
  "juridiction": "nom complet de la juridiction",
  "chambre": "ex: Chambre civile 2",
  "date_decision": "YYYY-MM-DD",
  "annee_decision": "YYYY",
  "numero_pourvoi": "ex: 89-61.265",
  "reference_complete": "ex: Cass. 2e civ., 12 oct. 1989, n° 89-61.265",
  "dispositif": "Cassation|Rejet|Irrecevabilité|Annulation|Confirmation|Infirmation",
  "parties": ["Partie 1", "Partie 2"],
  "president": "nom du président si mentionné",
  "type_document": "arret|jugement|ordonnance"
}""",
        "rules": (
            "- Les dates DOIVENT être en format ISO: YYYY-MM-DD\n"
            "- Le dispositif doit être parmi: Cassation, Rejet, Irrecevabilité, Annulation, Confirmation, Infirmation, null\n"
            "- La juridiction doit être normalisée: Cour de cassation, Cour d'appel, Tribunal judiciaire"
        )
    },
    "municipal": {
        "context": "expert en analyse de documents administratifs et municipaux français",
        "fields": """{
  "collectivite": "ex: Mairie de Paris, Commune de Lyon",
  "type_document": "deliberation|arrete|compte_rendu|budget|permis|autre",
  "numero_deliberation": "ex: 2024-001 ou n° 2024/03/15-01",
  "date_decision": "YYYY-MM-DD",
  "annee_decision": "YYYY",
  "seance_date": "YYYY-MM-DD (date de la séance du conseil)",
  "objet": "intitulé court du sujet traité",
  "rapporteur": "nom de l'élu ou du service rapporteur",
  "service_emetteur": "ex: Direction des travaux, DRH, Service urbanisme",
  "vote_resultat": "Adopté|Rejeté|Ajourné|Unanimité|null",
  "reference_complete": "ex: Délibération n° 2024-042 du 15 mars 2024 — Mairie de Lyon"
}""",
        "rules": (
            "- Les dates DOIVENT être en format ISO: YYYY-MM-DD\n"
            "- Le vote_resultat doit être parmi: Adopté, Rejeté, Ajourné, Unanimité, null\n"
            "- L'objet doit être une phrase courte résumant le sujet (max 100 caractères)\n"
            "- Si le document est un arrêté du maire, type_document = 'arrete'"
        )
    },
    "medical": {
        "context": "expert en analyse de documents médicaux",
        "fields": """{
  "type_document": "compte_rendu|ordonnance|bilan|rapport",
  "date_decision": "YYYY-MM-DD",
  "service_emetteur": "ex: Service cardiologie",
  "objet": "motif de consultation ou titre du document",
  "reference_complete": "référence du document"
}""",
        "rules": "- Les dates DOIVENT être en format ISO: YYYY-MM-DD"
    },
    "rh": {
        "context": "expert en analyse de documents RH",
        "fields": """{
  "type_document": "fiche_poste|contrat|evaluation|politique",
  "date_decision": "YYYY-MM-DD",
  "service_emetteur": "ex: Direction RH",
  "objet": "intitulé du poste ou sujet du document",
  "reference_complete": "référence du document"
}""",
        "rules": "- Les dates DOIVENT être en format ISO: YYYY-MM-DD"
    },
}


class LLMMetadataExtractor:
    """
    Extraction de métadonnées par LLM local (Ollama).
    Adapte automatiquement le prompt selon le DOMAIN configuré.
    """

    @staticmethod
    def extract_legal_metadata(text: str, source_type: str = "pdf") -> Dict[str, Any]:
        """
        Extraction structurée de métadonnées — délègue au domaine actif.
        Nom conservé pour rétrocompatibilité des imports.
        """
        return LLMMetadataExtractor.extract_metadata(text, domain=DOMAIN)

    @staticmethod
    def extract_metadata(text: str, domain: str = None) -> Dict[str, Any]:
        """
        Extraction générique selon le domaine.
        """
        active_domain = domain or DOMAIN
        cfg = EXTRACTION_PROMPTS.get(active_domain, EXTRACTION_PROMPTS["legal"])

        print(f"  🤖 Extraction métadonnées [{active_domain.upper()}] par LLM...")

        prompt = f"""Tu es un {cfg['context']}.
Voici le début d'un document. Extrait les métadonnées sous forme JSON stricte.

RÈGLES CRITIQUES:
- Si une information est absente, mets null (pas de chaîne vide)
- N'invente AUCUNE information, sois factuel
{cfg['rules']}

Format JSON attendu:
{cfg['fields']}

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
            metadata = LLMMetadataExtractor._validate_metadata(metadata, active_domain)

            label = metadata.get('reference_complete') or metadata.get('objet') or 'N/A'
            print(f"  ✅ Métadonnées extraites: {label}")
            return metadata

        except json.JSONDecodeError as e:
            print(f"  ⚠️ Erreur parsing JSON LLM: {e}")
            return {}
        except Exception as e:
            print(f"  ⚠️ Erreur extraction LLM: {e}")
            return {}

    @staticmethod
    def _validate_metadata(metadata: Dict, domain: str) -> Dict:
        """Validation et normalisation selon le domaine."""

        # Validation date ISO (commun à tous les domaines)
        for date_field in ['date_decision', 'seance_date']:
            if metadata.get(date_field):
                try:
                    datetime.fromisoformat(metadata[date_field])
                except ValueError:
                    print(f"  ⚠️ Date invalide: {metadata[date_field]}")
                    metadata[date_field] = None

        if not metadata.get('annee_decision') and metadata.get('date_decision'):
            metadata['annee_decision'] = metadata['date_decision'][:4]

        # Normalisation spécifique domaine
        if domain == "legal":
            dispositif_mapping = {
                'cassation': 'Cassation', 'rejet': 'Rejet',
                'irrecevabilité': 'Irrecevabilité', 'irrecevabilite': 'Irrecevabilité',
                'annulation': 'Annulation', 'confirmation': 'Confirmation',
                'infirmation': 'Infirmation'
            }
            if metadata.get('dispositif'):
                metadata['dispositif'] = dispositif_mapping.get(
                    metadata['dispositif'].lower(), metadata['dispositif']
                )

        elif domain == "municipal":
            vote_mapping = {
                'adopté': 'Adopté', 'adopte': 'Adopté',
                'rejeté': 'Rejeté', 'rejete': 'Rejeté',
                'ajourné': 'Ajourné', 'ajourne': 'Ajourné',
                'unanimité': 'Unanimité', 'unanimite': 'Unanimité',
            }
            if metadata.get('vote_resultat'):
                metadata['vote_resultat'] = vote_mapping.get(
                    metadata['vote_resultat'].lower(), metadata['vote_resultat']
                )

        return metadata
