import re
import os
import json
import argparse
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from legal_rag.pipeline import IngestionPipeline
from legal_rag.generation import AnswerGenerator

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


@app.route("/")
def index():
    return render_template("index.html")


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
    results = pipeline.search(query=query, n_results=5)

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
    for i, meta in enumerate(results["metadatas"][0]):
        dist = distances[i] if i < len(distances) else None
        raw = meta.get("source_file", "")
        label = raw.split("/")[-1].split("\\")[-1] or raw or "source"
        sources.append({"label": label, "dist": round(dist, 2) if dist is not None else None})

    def generate():
        for token in generator.stream_answer(query, results):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield f"data: {json.dumps({'done': True, 'sources': sources})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=False, port=args.port, threaded=True)
