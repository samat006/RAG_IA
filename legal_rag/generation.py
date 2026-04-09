from typing import List, Dict
from .config import mistral_client

class LegalAnswerGenerator:
    """
    Générateur de réponses juridiques basé sur les documents récupérés (RAG).
    Utilise Mistral AI.
    """
    
    def __init__(self):
        print(f"  🤖 Initialisation du générateur (Provider: MISTRAL)")

    def generate_answer(self, query: str, results: Dict) -> str:
        """
        Génère une réponse synthétique à partir des documents trouvés.
        """
        print(f"\n📝 Génération de la réponse pour: '{query}'")
        
        context = self._build_context(results)
        
        if not context:
            return "Je n'ai trouvé aucun document pertinent pour répondre à votre question."

        prompt = f"""Tu es un assistant juridique expert.
Ta mission est de répondre à la question de l'utilisateur en te basant UNIQUEMENT sur les documents fournis ci-dessous.

RÈGLES:
1. Cite tes sources précisément (ex: "Selon l'arrêt du 22 nov 1989...").
2. Si les documents ne contiennent pas la réponse, dis-le clairement.
3. Sois précis, factuel et synthétique.
4. Utilise un ton professionnel.

DOCUMENTS:
{context}

QUESTION:
{query}

RÉPONSE:"""

        try:
            return self._generate_mistral(prompt)
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

    def _generate_mistral(self, prompt: str) -> str:
        if not mistral_client:
            return "Erreur: Client Mistral non initialisé."
            
        response = mistral_client.chat.complete(
            model="mistral-large-latest", # Modèle plus performant pour la synthèse
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
