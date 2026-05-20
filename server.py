import re
import os
import json
import argparse
from flask import Flask, request, jsonify, render_template, Response, stream_with_context, send_from_directory
from legal_rag.pipeline import IngestionPipeline
from legal_rag.generation import AnswerGenerator
from legal_rag.config import MAX_DISTANCE

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="phi3", help="Modèle Ollama à utiliser (ex: phi3, mistral)")
parser.add_argument("--port",  default=5000, type=int)
args, _ = parser.parse_known_args()

os.environ["GENERATION_MODEL"] = args.model

app = Flask(__name__)

pipeline = IngestionPipeline(collection_name="legal_corpus_m2_tp", retriever_type="recursive")
pipeline.ingest_corpus("./documents/test")
generator = AnswerGenerator()
print(f"🤖 Modèle : {generator.model}")

GREETINGS = re.compile(
    r"^\s*(bonjour|bonsoir|salut|hello|hi|coucou|hey|bonne\s+journée|bonne\s+soirée)[!?,.\s]*$",
    re.IGNORECASE
)


DOCS_DIR = os.path.abspath("./documents/test")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/documents/<path:filename>")
def serve_document(filename):
    return send_from_directory(DOCS_DIR, filename)


@app.route("/ask", methods=["POST"])
def ask():
    query = request.json.get("query", "").strip()
    if not query:
        return jsonify({"error": "Question vide"}), 400

    # Salutations — réponse directe sans RAG
    if GREETINGS.match(query):
        def greet():
            msg = "Bonjour ! Je suis votre assistant touristique pour Corte et le Centre-Corse. Posez-moi une question sur les hébergements, activités ou le patrimoine."
            yield f"data: {json.dumps({'token': msg})}\n\n"
            yield f"data: {json.dumps({'done': True, 'sources': []})}\n\n"
        return Response(stream_with_context(greet()), mimetype="text/event-stream")

    # Retrieval
    results = pipeline.search(query=query, n_results=8)

    no_ids = not results or not results.get("ids") or not results["ids"][0]
    if no_ids:
        def no_res():
            yield f"data: {json.dumps({'error': 'no_results'})}\n\n"
        return Response(stream_with_context(no_res()), mimetype="text/event-stream")

    context = generator.build_context(results)
    if not context:
        def no_ctx():
            yield f"data: {json.dumps({'error': 'no_context'})}\n\n"
        return Response(stream_with_context(no_ctx()), mimetype="text/event-stream")

    # Sources
    sources = []
    distances = results.get("distances", [[]])[0]
    seen = set()
    for i, meta in enumerate(results["metadatas"][0]):
        dist = distances[i] if i < len(distances) else None
        if dist is not None and dist > MAX_DISTANCE:
            continue  # même filtre que _build_context
        raw = meta.get("source_file", "")
        source_type = meta.get("source_type", "")
        filename = raw.split("/")[-1].split("\\")[-1] or raw or "source"
        if source_type == "web":
            url = raw
        else:
            url = f"/documents/{filename}"
        key = filename
        if key in seen:
            continue
        seen.add(key)
        sources.append({"label": filename, "url": url, "dist": round(dist, 2) if dist is not None else None})

    NO_INFO = "je n'ai pas cette information"

    def generate():
        full = ""
        for token in generator.stream_answer(query, results):
            full += token
            yield f"data: {json.dumps({'token': token})}\n\n"
        # Si le LLM dit qu'il n'a pas l'info, on masque les sources
        show_sources = sources if NO_INFO not in full.lower() else []
        yield f"data: {json.dumps({'done': True, 'sources': show_sources})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=False, port=args.port, threaded=True)
