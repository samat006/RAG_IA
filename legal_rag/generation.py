from typing import List, Dict
import ollama
from .config import GENERATION_MODEL

class LegalAnswerGenerator:
    """
    Générateur de réponses basé sur les documents récupérés (RAG).
    Utilise Ollama en local (100% gratuit).
    """

    def __init__(self):
        print(f"  🤖 Initialisation du générateur (Provider: OLLAMA local — {GENERATION_MODEL})")

    def generate_answer(self, query: str, results: Dict) -> str:
        """
        Génère une réponse synthétique à partir des documents trouvés.
        """
        print(f"\n📝 Génération de la réponse pour: '{query}'")

        context = self._build_context(results)

        if not context:
            return "Je n'ai trouvé aucun document pertinent pour répondre à votre question."

        prompt = f"""Tu es un assistant expert en analyse documentaire.
Ta mission est de répondre à la question de l'utilisateur en te basant UNIQUEMENT sur les documents fournis ci-dessous.

RÈGLES:
1. Cite tes sources précisément (ex: "Selon le document X...").
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
        """Construit le contexte textuel à partir des résultats de recherche."""
        context_parts = []

        if not results or not results['ids'] or not results['ids'][0]:
            return ""

        for i, (doc, metadata) in enumerate(zip(results['documents'][0], results['metadatas'][0]), 1):
            ref = metadata.get('reference_complete', 'Document sans référence')
            type_doc = metadata.get('type_document', 'N/A')
            context_parts.append(f"--- DOCUMENT {i} ({type_doc}) ---\nRéférence: {ref}\nContenu: {doc}\n")

        return "\n".join(context_parts)

    def _generate_ollama(self, prompt: str) -> str:
        response = ollama.chat(
            model=GENERATION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}
        )
        return response.message.content
