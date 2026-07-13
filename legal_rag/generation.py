from typing import Dict
import json
import httpx
import ollama
from .config import MISTRAL_API_KEY, DOMAIN, settings

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

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
    Générateur de réponses RAG — deux backends interchangeables, choisis via
    /admin/settings (config.settings.GENERATION_BACKEND) :
      - "mistral_api"  : API Mistral Cloud (httpx)
      - "ollama_local" : Ollama en local (100% offline, zéro coût)
    Le reste du pipeline (prompt, filtrage par distance, streaming) est identique
    quel que soit le backend.
    """

    def __init__(self):
        self.domain = DOMAIN
        self.backend = settings.GENERATION_BACKEND
        self.model = settings.GENERATION_MODEL
        # Instance (pas classe) : chaque nouvelle génération d'AnswerGenerator
        # (reload_generator() après un changement de réglage) capture la valeur
        # courante — un attribut de classe resterait figé sur la 1ère valeur lue.
        self.max_distance = settings.MAX_DISTANCE
        self.system_intro = DOMAIN_PROMPTS.get(DOMAIN, DOMAIN_PROMPTS["tourisme"])
        self.headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json",
        }
        print(f"  🤖 Générateur initialisé — domaine : {DOMAIN.upper()} | backend : {self.backend} | modèle : {self.model}")

    # ── Mistral API (httpx) ──────────────────────────────────────────────
    def _post(self, messages: list, max_tokens: int = None) -> httpx.Response:
        payload = {"model": self.model, "messages": messages, "temperature": 0.0, "stream": False}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        return httpx.post(MISTRAL_URL, headers=self.headers, json=payload, timeout=120)

    def _chat_mistral(self, messages: list, max_tokens: int = None) -> str:
        resp = self._post(messages, max_tokens=max_tokens)
        return resp.json()["choices"][0]["message"]["content"]

    def _stream_mistral(self, messages: list):
        payload = {"model": self.model, "messages": messages, "temperature": 0.0, "stream": True}
        with httpx.stream("POST", MISTRAL_URL, headers=self.headers, json=payload, timeout=120) as resp:
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    token = json.loads(data)["choices"][0]["delta"].get("content", "")
                    if token:
                        yield token
                except Exception:
                    continue

    # ── Ollama local ──────────────────────────────────────────────────────
    def _chat_ollama(self, messages: list, max_tokens: int = None) -> str:
        options = {"temperature": 0.0}
        if max_tokens:
            options["num_predict"] = max_tokens
        resp = ollama.chat(model=self.model, messages=messages, options=options)
        return resp.message.content

    def _stream_ollama(self, messages: list):
        stream = ollama.chat(model=self.model, messages=messages, stream=True, options={"temperature": 0.0})
        for chunk in stream:
            token = chunk.message.content
            if token:
                yield token

    # ── Backend dispatch ──────────────────────────────────────────────────
    def _chat(self, messages: list, max_tokens: int = None) -> str:
        if self.backend == "ollama_local":
            return self._chat_ollama(messages, max_tokens=max_tokens)
        return self._chat_mistral(messages, max_tokens=max_tokens)

    def _stream(self, messages: list):
        if self.backend == "ollama_local":
            yield from self._stream_ollama(messages)
        else:
            yield from self._stream_mistral(messages)

    def build_context(self, results: Dict) -> str:
        return self._build_context(results)

    def build_prompt(self, query: str, results: Dict) -> str:
        context = self._build_context(results)
        if not context:
            return ""
        return f"""{self.system_intro}

Règles strictes :
- Réponds UNIQUEMENT à ce qui est demandé, de façon courte et directe n'invate jamais jamais.
- Utilise SEULEMENT les passages qui répondent précisément à la question, ignore les autres.
- Ne mélange pas plusieurs sujets dans la même réponse.
- Si la question contient une faute de frappe, interprète-la intelligemment.
- Cite  les sources des URL interne  dans ta réponse, mais cite pas pdf.
- Si l'information est absente des passages, réponds uniquement : "Je n'ai pas cette information dans les documents."
- Jamais de connaissance générale, jamais d'invention.

PASSAGES :
{context}

QUESTION : {query}
RÉPONSE (courte et directe) :"""

    def rewrite_query(self, query: str, history: list) -> str:
        if not history:
            return query
        last = "\n".join(f"{m['role'].capitalize()} : {m['content']}" for m in history[-4:])
        prompt = (
            "Tu es un assistant qui reformule des questions de suivi en questions autonomes.\n"
            "RÈGLES STRICTES :\n"
            "- Si la question porte sur un sujet DIFFÉRENT de la conversation (changement de thème), "
            "retourne la question TELLE QUELLE sans modification.\n"
            "- Reformule UNIQUEMENT si la question est une suite directe du même sujet.\n"
            "- Réponds UNIQUEMENT avec la question (reformulée ou originale), rien d'autre.\n\n"
            f"Conversation :\n{last}\n\nQuestion : {query}\nQuestion reformulée :"
        )
        try:
            rewritten = self._chat([{"role": "user", "content": prompt}], max_tokens=60)
            rewritten = rewritten.strip().split("\n")[0].strip().strip('"').strip("'")
            print(f"   ✏️  Reformulée : {rewritten!r}")
            return rewritten if rewritten else query
        except Exception as e:
            print(f"   ⚠️  Rewrite échoué : {e}")
            return query

    def stream_answer(self, query: str, results: Dict, history: list = None):
        prompt = self.build_prompt(query, results)
        if not prompt:
            return
        messages = [{"role": "system", "content": self.system_intro}]
        for msg in (history or []):
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": prompt})

        yield from self._stream(messages)

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
            return self._chat(messages)
        except Exception as e:
            return f"❌ Erreur lors de la génération: {e}"

    def _build_context(self, results: Dict) -> str:
        context_parts = []
        if not results or not results['ids'] or not results['ids'][0]:
            return ""
        distances = results.get('distances', [[]])[0]
        for i, (doc, metadata) in enumerate(zip(results['documents'][0], results['metadatas'][0]), 1):
            dist = distances[i - 1] if distances and i - 1 < len(distances) else 0
            if dist > self.max_distance:
                print(f"    ⏭️  Chunk {i} ignoré (distance={dist:.3f} > {self.max_distance})")
                continue
            source = metadata.get('source_file', 'source inconnue')
            source_type = metadata.get('source_type', 'inconnu')
            label = f"URL : {source}" if source_type == "web" else f"Document : {source}"
            context_parts.append(f"[{label}]\n{doc}")
        return "\n\n---\n\n".join(context_parts)
