from typing import Dict
import ollama
from .config import GENERATION_MODEL, DOMAIN, MAX_DISTANCE

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


class AnswerGenerator:
    """
    Générateur de réponses RAG — multi-domaine, 100% local (Ollama).
    Le comportement s'adapte automatiquement au DOMAIN configuré.
    """

    def __init__(self):
        self.domain = DOMAIN
        self.model = GENERATION_MODEL
        self.system_intro = DOMAIN_PROMPTS.get(DOMAIN, DOMAIN_PROMPTS["tourisme"])
        print(f"  🤖 Générateur initialisé — domaine : {DOMAIN.upper()} | modèle : {self.model}")

    # Seuil max de distance L2 normalisée (nomic-embed-text, vecteurs unitaires)
    # 0=identique, 1.41=orthogonal, 2=opposé
    # 1.5 = cosine_similarity > 0 (chunk au moins vaguement lié à la query)
    MAX_DISTANCE = MAX_DISTANCE

    def build_context(self, results: Dict) -> str:
        """Public — permet de vérifier le contexte avant d'appeler le LLM."""
        return self._build_context(results)

    def build_prompt(self, query: str, results: Dict) -> str:
        """Construit le prompt complet — utilisé par generate_answer et stream_answer."""
        context = self._build_context(results)
        if not context:
            return ""
        return f"""{self.system_intro}

Règles strictes :
- Réponds UNIQUEMENT à ce qui est demandé, de façon courte et directe.
- Utilise SEULEMENT les passages qui répondent précisément à la question, ignore les autres.
- Ne mélange pas plusieurs sujets dans la même réponse.
- Si la question contient une faute de frappe, interprète-la intelligemment.
- Ne cite jamais les sources dans ta réponse, elles sont affichées séparément.
- Si l'information est absente des passages, réponds uniquement : "Je n'ai pas cette information veuillez me fournir plus de détails s'il vous plaît."
- Jamais de connaissance générale, jamais d'invention.

PASSAGES :
{context}

QUESTION : {query}
RÉPONSE (courte et directe) :"""
#-cite toujours la source de chaque information utilisée (ex: "source: le document X...").

    def stream_answer(self, query: str, results: Dict):
        """Génère la réponse token par token — même pipeline que generate_answer."""
        prompt = self.build_prompt(query, results)
        if not prompt:
            return
        stream = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            options={"temperature": 0.0}
        )
        for chunk in stream:
            token = chunk.message.content
            if token:
                yield token

    def generate_answer(self, query: str, results: Dict) -> str:
        print(f"\n📝 Génération [{self.domain.upper()}] : '{query}'")
        prompt = self.build_prompt(query, results)
        if not prompt:
            return "Je n'ai trouvé aucun passage pertinent dans les documents pour répondre à cette question."
        try:
            return self._generate_ollama(prompt)
        except Exception as e:
            return f"❌ Erreur lors de la génération: {e}"

    def _build_context(self, results: Dict) -> str:
        """
        Construit le contexte en filtrant les chunks trop éloignés.
        Chaque passage est préfixé de sa source (fichier local ou URL web).
        Retourne "" si aucun chunk pertinent → le générateur refusera de répondre.
        """
        context_parts = []
        if not results or not results['ids'] or not results['ids'][0]:
            return ""

        distances = results.get('distances', [[]])[0]

        for i, (doc, metadata) in enumerate(zip(results['documents'][0], results['metadatas'][0]), 1):
            dist = distances[i - 1] if distances and i - 1 < len(distances) else 0
            if dist > self.MAX_DISTANCE:
                print(f"    ⏭️  Chunk {i} ignoré (distance={dist:.3f} > {self.MAX_DISTANCE})")
                continue

            source = metadata.get('source_file', 'source inconnue')
            source_type = metadata.get('source_type', 'inconnu')
            label = f"URL : {source}" if source_type == "web" else f"Document : {source}"
            context_parts.append(f"[{label}]\n{doc}")

        return "\n\n---\n\n".join(context_parts)

    def _generate_ollama(self, prompt: str) -> str:
        response = ollama.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0}
        )
        return response.message.content