import re
import os
import json
import argparse
import threading
from flask import Flask, request, jsonify, render_template, Response, stream_with_context, send_from_directory
from flask_cors import CORS
from legal_rag.pipeline import IngestionPipeline
from legal_rag.generation import AnswerGenerator
from legal_rag.config import MAX_DISTANCE
from clients import CLIENTS, LOCAL

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="mistral", help="Modèle Ollama")
parser.add_argument("--port",  default=5000, type=int)
args, _ = parser.parse_known_args()

os.environ["GENERATION_MODEL"] = args.model

app = Flask(__name__, static_folder="static")
CORS(app)  # autorise les appels depuis n'importe quel domaine

# ── Pipelines (config dans clients.py) ───────────────────────────────────────
LOCAL_PIPELINE = IngestionPipeline(collection_name=LOCAL["collection"], retriever_type="recursive")
LOCAL_PIPELINE.ingest_corpus(LOCAL["corpus"])

PIPELINES = {}
for key, cfg in CLIENTS.items():
    if os.path.exists(cfg["corpus"]):
        p = IngestionPipeline(collection_name=cfg["collection"], retriever_type="recursive")
        p.ingest_corpus(cfg["corpus"], web_sources=cfg.get("web_sources", []))
        PIPELINES[key] = p
        print(f"✅ Pipeline chargé : {cfg['name']}")
    else:
        print(f"⚠️  Dossier introuvable pour {cfg['name']} : {cfg['corpus']}")

generator = AnswerGenerator()
print(f"🤖 Modèle : {generator.model}")

GREETINGS = re.compile(
    r"^\s*(bonjour|bonsoir|salut|hello|hi|coucou|hey|bonne\s+journée|bonne\s+soirée)[!?,.\s]*$",
    re.IGNORECASE
)


STATIC_DIR = os.path.abspath("./static")


ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-moi")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin/index/<client_key>", methods=["POST"])
def admin_index(client_key):
    token = request.headers.get("X-Admin-Token", "")
    if token != ADMIN_TOKEN:
        return jsonify({"error": "Non autorisé"}), 401

    if client_key not in CLIENTS:
        return jsonify({"error": "Client inconnu"}), 404

    cfg   = CLIENTS[client_key]
    reset = request.json.get("reset", False) if request.json else False

    def run():
        p = IngestionPipeline(collection_name=cfg["collection"], retriever_type="recursive")
        p.ingest_corpus(cfg["corpus"], force=reset, web_sources=cfg.get("web_sources", []))
        PIPELINES[client_key] = p
        print(f"✅ Re-indexation terminée : {cfg['name']}")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "indexation démarrée", "client": cfg["name"]})


@app.route("/widget.js")
def widget():
    return send_from_directory(STATIC_DIR, "widget.js",
                               mimetype="application/javascript")


@app.route("/test")
def test_page():
    path = os.path.join(STATIC_DIR, "test_widget.html")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    resp = app.response_class(content, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


@app.route("/documents/<client_key>/<path:filename>")
def serve_document(client_key, filename):
    if client_key == "local":
        base = os.path.abspath(LOCAL["corpus"])
    elif client_key in CLIENTS:
        base = os.path.abspath(CLIENTS[client_key]["corpus"])
    else:
        return "Client inconnu", 404
    return send_from_directory(base, filename)


@app.route("/ask", methods=["POST"])
def ask():
    data = request.json or {}
    query = data.get("query", "").strip()
    api_key = data.get("key", "")

    if not query:
        return jsonify({"error": "Question vide"}), 400

    # Vérification clé API et sélection du bon pipeline
    if api_key and api_key not in CLIENTS:
        return jsonify({"error": "Clé API invalide"}), 403

    client_name = CLIENTS[api_key]["name"] if api_key in CLIENTS else "local"
    active_pipeline = PIPELINES.get(api_key, LOCAL_PIPELINE)
    print(f"📥 [{client_name}] {query}")

    # Salutations
    if GREETINGS.match(query):
        def greet():
            msg = "Bonjour ! Je suis votre assistant touristique. Posez-moi une question sur les hébergements, activités ou le patrimoine."
            yield f"data: {json.dumps({'token': msg})}\n\n"
            yield f"data: {json.dumps({'done': True, 'sources': []})}\n\n"
        return Response(stream_with_context(greet()), mimetype="text/event-stream")

    # Retrieval
    results = active_pipeline.search(query=query, n_results=8)

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
            continue
        raw = meta.get("source_file", "")
        source_type = meta.get("source_type", "")
        filename = raw.split("/")[-1].split("\\")[-1] or raw or "source"
        print(f"   🗂️  source_file={raw!r}  filename={filename!r}  type={source_type!r}")
        if source_type == "web":
            url = raw
        else:
            client_key = api_key if api_key else "local"
            url = f"/documents/{client_key}/{filename}"
        if filename in seen:
            continue
        seen.add(filename)
        sources.append({"label": filename, "url": url, "dist": round(dist, 2) if dist is not None else None})

    NO_INFO = "je n'ai pas cette information"

    def generate():
        full = ""
        for token in generator.stream_answer(query, results):
            full += token
            yield f"data: {json.dumps({'token': token})}\n\n"
        show_sources = sources if NO_INFO not in full.lower() else []
        yield f"data: {json.dumps({'done': True, 'sources': show_sources})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=False, port=args.port, threaded=True)
