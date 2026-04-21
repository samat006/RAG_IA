from typing import Dict
import ollama
from .config import GENERATION_MODEL, DOMAIN

# ── Personnalité de l'assistant par domaine ──────────────────────────────────
DOMAIN_PROMPTS = {
    "legal": (
        "Tu es un assistant juridique expert.\n"
        "Ta mission est de répondre à la question en te basant UNIQUEMENT sur les documents fournis.\n"
        "Cite tes sources précisément (ex: 'Selon l'arrêt du 22 nov 1989...')."
    ),
    "municipal": (
        "Tu es un assistant spécialisé en documents administratifs municipaux.\n"
        "Ta mission est de répondre à la question en te basant UNIQUEMENT sur les documents fournis.\n"
        "Cite tes sources précisément (ex: 'Selon la délibération n° 2024-042 de la Mairie de Lyon...')."
    ),
    "medical": (
        "Tu es un assistant spécialisé en analyse de documents médicaux.\n"
        "Ta mission est de répondre à la question en te basant UNIQUEMENT sur les documents fournis.\n"
        "Cite tes sources précisément."
    ),
    "rh": (
        "Tu es un assistant spécialisé en ressources humaines.\n"
        "Ta mission est de répondre à la question en te basant UNIQUEMENT sur les documents fournis.\n"
        "Cite tes sources précisément."
    ),
    "technique": (
        "Tu es un assistant spécialisé en documentation technique.\n"
        "Ta mission est de répondre à la question en te basant UNIQUEMENT sur les documents fournis.\n"
        "Cite tes sources précisément."
    ),
    "tourisme": (
        "Tu es un assistant spécialisé en documentation touristique.\n"
        "Ta mission est de répondre à la question en te basant UNIQUEMENT sur les documents fournis.\n"
        "Cite tes sources précisément."
    )
}


class LegalAnswerGenerator:
    """
    Générateur de réponses RAG — multi-domaine, 100% local (Ollama).
    Le comportement s'adapte automatiquement au DOMAIN configuré.
    """

    def __init__(self):
        self.domain = DOMAIN
        self.system_intro = DOMAIN_PROMPTS.get(DOMAIN, DOMAIN_PROMPTS["legal"])
        print(f"  🤖 Générateur initialisé — domaine : {DOMAIN.upper()} | modèle : {GENERATION_MODEL}")

    def generate_answer(self, query: str, results: Dict) -> str:
        print(f"\n📝 Génération [{self.domain.upper()}] : '{query}'")

        context = self._build_context(results)
        if not context:
            return "Je n'ai trouvé aucun document pertinent pour répondre à votre question."

        prompt = f"""{self.system_intro}

RÈGLES:
1. Cite tes sources précisément.
2. Si les documents ne contiennent pas la réponse, dis-le clairement.
3. Sois précis, factuel et synthétique.
4. Utilise un ton professionnel.

DOCUMENTS:
{context}

QUESTION:
{query}

RÉPONSE:"""

        try:
            return self._generate_ollama(prompt)
        except Exception as e:
            return f"❌ Erreur lors de la génération: {e}"

    def _build_context(self, results: Dict) -> str:
        context_parts = []
        if not results or not results['ids'] or not results['ids'][0]:
            return ""
        for i, (doc, metadata) in enumerate(zip(results['documents'][0], results['metadatas'][0]), 1):
            # Libellé de référence adapté au domaine
            if self.domain == "municipal":
                ref = (
                    metadata.get('reference_complete')
                    or metadata.get('objet')
                    or metadata.get('numero_deliberation')
                    or 'Document sans référence'
                )
            else:
                ref = metadata.get('reference_complete', 'Document sans référence')

            type_doc = metadata.get('type_document', 'N/A')
            context_parts.append(
                f"--- DOCUMENT {i} ({type_doc}) ---\nRéférence: {ref}\nContenu: {doc}\n"
            )
        return "\n".join(context_parts)

    def _generate_ollama(self, prompt: str) -> str:
        response = ollama.chat(
            model=GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}
        )
        return response.message.content
