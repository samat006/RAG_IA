from typing import Dict
import ollama
from .config import GENERATION_MODEL, DOMAIN, MAX_DISTANCE

# ── Personnalité de l'assistant par domaine ──────────────────────────────────
DOMAIN_PROMPTS = {
    "legal":     "Tu es un assistant juridique expert. Réponds en te basant UNIQUEMENT sur les documents fournis.",
    "municipal": "Tu es un assistant spécialisé en documents administratifs municipaux. Réponds en te basant UNIQUEMENT sur les documents fournis.",
    "medical":   "Tu es un assistant spécialisé en analyse de documents médicaux. Réponds en te basant UNIQUEMENT sur les documents fournis.",
    "rh":        "Tu es un assistant spécialisé en ressources humaines. Réponds en te basant UNIQUEMENT sur les documents fournis.",
    "technique": "Tu es un assistant spécialisé en documentation technique. Réponds en te basant UNIQUEMENT sur les documents fournis.",
    "tourisme":  "Tu es un assistant spécialisé en tourisme. Réponds en te basant UNIQUEMENT sur les documents fournis.",
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
- Réponds UNIQUEMENT à ce qui est demandé, de façon courte et directe n'invate jamais jamais.
- Utilise SEULEMENT les passages qui répondent précisément à la question, ignore les autres.
- Ne mélange pas plusieurs sujets dans la même réponse.
- Si la question contient une faute de frappe, interprète-la intelligemment.
- Ne cite jamais les sources dans ta réponse, elles sont affichées séparément.
- Si l'information est absente des passages, réponds uniquement : "Je n'ai pas cette information dans les documents."
- Jamais de connaissance générale, jamais d'invention.

PASSAGES :
{context}

QUESTION : {query}
RÉPONSE (courte et directe) :"""
#. -cite toujours la source de chaque information utilisée (ex: "source: le document X...").

    REWRITE_MODEL = "phi3"

    def rewrite_query(self, query: str, history: list) -> str:
        """Reformule la question en autonome en intégrant l'historique de conversation."""
        if not history:
            return query
        last = "\n".join(f"{m['role'].capitalize()} : {m['content']}" for m in history[-4:])
        prompt = (
            "Tu es un assistant qui reformule des questions de suivi en questions autonomes.\n"
            "RÈGLES STRICTES :\n"
            "- Si la question porte sur un sujet DIFFÉRENT de la conversation (changement de thème), "
            "retourne la question TELLE QUELLE sans modification.\n"
            "- Reformule UNIQUEMENT si la question est une suite directe du même sujet "
            "(ex: 'et lui ?', 'combien ?', 'pourquoi ?' en référence à ce qui précède).\n"
            "- Ne mélange JAMAIS des entités, noms ou sujets de l'historique dans la nouvelle question "
            "si elle porte sur un autre sujet.\n"
            "- Réponds UNIQUEMENT avec la question (reformulée ou originale), rien d'autre.\n\n"
            f"Conversation :\n{last}\n\nQuestion : {query}\nQuestion reformulée :"
        )
        try:
            resp = ollama.chat(
                model=self.REWRITE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0, "num_predict": 60}
            )
            rewritten = resp.message.content.strip().split("\n")[0].strip().strip('"').strip("'")
            print(f"   ✏️  Reformulée : {rewritten!r}")
            return rewritten if rewritten else query
        except Exception as e:
            print(f"   ⚠️  Rewrite échoué : {e}")
            return query

    def stream_answer(self, query: str, results: Dict, history: list = None):
        """Génère la réponse token par token avec historique de conversation optionnel."""
        prompt = self.build_prompt(query, results)
        if not prompt:
            return
        messages = [{"role": "system", "content": self.system_intro}]
        for msg in (history or []):
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": prompt})
        stream = ollama.chat(model=self.model, messages=messages, stream=True, options={"temperature": 0.0})
        for chunk in stream:
            token = chunk.message.content
            if token:
                yield token

    def generate_answer(self, query: str, results: Dict, history: list = None) -> str:
        print(f"\n📝 Génération [{self.domain.upper()}] : '{query}'")
        prompt = self.build_prompt(query, results)
        if not prompt:
            return "Je n'ai trouvé aucun passage pertinent dans les documents pour répondre à cette question."
        try:
            messages = [{"role": "system", "content": self.system_intro}]
            for msg in (history or []):
                messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": prompt})
            response = ollama.chat(model=self.model, messages=messages, options={"temperature": 0.0})
            return response.message.content
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