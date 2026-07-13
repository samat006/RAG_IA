import re
import os
import json
import time
import secrets
import argparse
import threading
from flask import Flask, request, jsonify, render_template, Response, stream_with_context, send_from_directory, session
from flask_cors import CORS
from legal_rag import config
from legal_rag.config import WEB_EXCLUDED_URLS, SOURCES_MAX_COUNT
import store
import runtime

parser = argparse.ArgumentParser()
parser.add_argument("--model", default=None,
                     help="Force le modèle de génération pour ce lancement (sinon réglage /admin/settings)")
parser.add_argument("--port",  default=5000, type=int,
                     help="Port PUBLIC (widget, /ask) — doit rester joignable depuis internet")
parser.add_argument("--host",  default="0.0.0.0",
                     help="Interface d'écoute du port public (0.0.0.0 = joignable depuis l'extérieur, "
                          "nécessaire pour que le widget fonctionne sur les sites clients)")
parser.add_argument("--admin-port", default=5001, type=int, dest="admin_port",
                     help="Port ADMIN (/admin/*) — n'écoute qu'en 127.0.0.1, jamais exposé sur le réseau. "
                          "Accès à distance via tunnel SSH : ssh -L <admin-port>:localhost:<admin-port> user@serveur")
args, _ = parser.parse_known_args()

app = Flask(__name__, static_folder="static")
CORS(app)  # autorise les appels depuis n'importe quel domaine

# Signature des sessions/cookies admin. Volontairement PAS de défaut faible
# statique (contrairement à ADMIN_TOKEN ci-dessous) : un secret de session
# prévisible permettrait de forger des cookies "admin=True". À défaut de
# variable d'environnement, on génère un secret aléatoire par démarrage —
# les sessions ne survivent pas à un redémarrage, ce qui est acceptable pour
# un panneau d'administration interne.
app.secret_key = os.environ.get("ADMIN_SESSION_SECRET") or secrets.token_hex(32)

# ── Réglages admin (store.py = source de vérité, clients.py = seed initial) ──
store.init_db()
config.sync_from_store()
if args.model:
    config.settings.GENERATION_MODEL = args.model  # override ponctuel, non persisté

# ── Pipelines + générateur (état partagé dans runtime.py, voir ce fichier
# pour le pourquoi : évite un piège de double-import __main__ vs `server`) ──
runtime.init_pipelines()
runtime.reload_generator()

GREETINGS = re.compile(
    r"^\s*(bonjour|bonsoir|salut|hello|hi|coucou|hey|bonne\s+journée|bonne\s+soirée)[!?,.\s]*$",
    re.IGNORECASE
)


STATIC_DIR   = os.path.abspath("./static")
ADMIN_TOKEN  = os.environ.get("ADMIN_TOKEN", "change-moi")
SESSION_TTL  = 30 * 60  # 30 min d'inactivité

SESSIONS: dict = {}
SESSIONS_LOCK = threading.Lock()

def get_history(session_id: str) -> list:
    with SESSIONS_LOCK:
        s = SESSIONS.get(session_id)
        if not s:
            return []
        s["last"] = time.time()
        return list(s["history"])

def save_exchange(session_id: str, user_msg: str, assistant_msg: str):
    with SESSIONS_LOCK:
        if session_id not in SESSIONS:
            SESSIONS[session_id] = {"history": [], "last": time.time()}
        h = SESSIONS[session_id]["history"]
        h.append({"role": "user",      "content": user_msg})
        h.append({"role": "assistant", "content": assistant_msg})
        if len(h) > 6:
            del h[:2]
        SESSIONS[session_id]["last"] = time.time()

def _cleanup_sessions():
    while True:
        time.sleep(300)
        cutoff = time.time() - SESSION_TTL
        with SESSIONS_LOCK:
            expired = [sid for sid, s in SESSIONS.items() if s["last"] < cutoff]
            for sid in expired:
                del SESSIONS[sid]
        if expired:
            print(f"🧹 {len(expired)} session(s) expirée(s)")

threading.Thread(target=_cleanup_sessions, daemon=True).start()

# Back-office admin (/admin/*)
from admin_routes import admin_bp
app.register_blueprint(admin_bp)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin/index/<client_key>", methods=["POST"])
def admin_index(client_key):
    """
    Ré-indexation d'un client ou du corpus local.
    Body JSON :
      { "mode": "docs"|"web"|"both",  (défaut: "both")
        "reset": true|false }         (défaut: true)
    Autorisé par X-Admin-Token (CLI/API) OU par une session admin active (back-office).
    """
    token = request.headers.get("X-Admin-Token", "")
    if token != ADMIN_TOKEN and not session.get("admin"):
        return jsonify({"error": "Non autorisé"}), 401

    body  = request.json or {}
    mode  = body.get("mode", "both")
    reset = body.get("reset", True)

    if mode not in ("docs", "web", "both"):
        return jsonify({"error": "mode invalide, valeurs : docs | web | both"}), 400

    cfg = store.get_client(client_key)
    if cfg is None:
        return jsonify({"error": "Client inconnu"}), 404

    runtime.trigger_reindex(client_key, mode=mode, reset=reset)
    return jsonify({"status": "indexation démarrée", "client": cfg["name"], "mode": mode})


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
    cfg = store.get_client(client_key)
    if cfg is None:
        return "Client inconnu", 404
    return send_from_directory(os.path.abspath(cfg["corpus_dir"]), filename)


@app.route("/ask", methods=["POST"])
def ask():
    data       = request.json or {}
    query      = data.get("query", "").strip()
    api_key    = data.get("key", "")
    session_id = data.get("session_id", "")

    if not query:
        return jsonify({"error": "Question vide"}), 400

    client_cfg = store.get_client(api_key) if api_key else None
    if api_key and client_cfg is None:
        return jsonify({"error": "Clé API invalide"}), 403

    client_name     = client_cfg["name"] if client_cfg else "local"
    active_pipeline = runtime.PIPELINES.get(api_key) if api_key else runtime.PIPELINES.get("local")
    if active_pipeline is None:
        # Cas rare : client valide mais pipeline pas encore enregistré (juste après
        # sa création). On refuse explicitement plutôt que de retomber sur le
        # pipeline local par défaut (ce qui serait une fuite de données inter-client).
        return jsonify({"error": "Ce client n'est pas encore prêt, réessayez dans un instant"}), 503

    history = get_history(session_id) if session_id else []
    print(f"📥 [{client_name}] {query} (session={session_id[:8] if session_id else 'none'})")

    # Salutations
    if GREETINGS.match(query):
        def greet():
            msg = "Bonjour ! Je suis votre assistant touristique. Posez-moi une question sur les hébergements, activités ou le patrimoine."
            yield f"data: {json.dumps({'token': msg})}\n\n"
            yield f"data: {json.dumps({'done': True, 'sources': []})}\n\n"
        return Response(stream_with_context(greet()), mimetype="text/event-stream")

    # Reformulation si question de suivi, puis retrieval
    search_query = runtime.generator.rewrite_query(query, history)
    print(f"   🔍 ChromaDB query : {search_query!r}")
    results = active_pipeline.search(query=search_query, n_results=config.settings.N_RESULTS)

    no_ids = not results or not results.get("ids") or not results["ids"][0]
    if no_ids:
        def no_res():
            yield f"data: {json.dumps({'error': 'no_results'})}\n\n"
        return Response(stream_with_context(no_res()), mimetype="text/event-stream")

    context = runtime.generator.build_context(results)
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
        if dist is not None and dist > config.settings.MAX_DISTANCE:
            continue
        raw = meta.get("source_file", "")
        source_type = meta.get("source_type", "")
        filename = raw.split("/")[-1].split("\\")[-1] or raw or "source"
        print(f"   🗂️  source_file={raw!r}  filename={filename!r}  type={source_type!r}")
        if source_type != "web":
            continue  # PDFs restent confidentiels : non transmis au client
        if any(pattern in raw for pattern in WEB_EXCLUDED_URLS if pattern):
            continue  # URL exclue (voir WEB_EXCLUDED_URLS)
        if raw in seen:
            continue
        seen.add(raw)
        sources.append({"label": filename, "url": raw, "dist": round(dist, 2) if dist is not None else None})
        if len(sources) >= SOURCES_MAX_COUNT:
            break

    NO_INFO = "je n'ai pas cette information"

    def generate():
        full = ""
        for token in runtime.generator.stream_answer(query, results, history=history):
            full += token
            yield f"data: {json.dumps({'token': token})}\n\n"
        show_sources = sources if NO_INFO not in full.lower() else []
        # Sauvegarder uniquement les échanges avec une vraie réponse
        if session_id and show_sources:
            save_exchange(session_id, query, full)
        yield f"data: {json.dumps({'done': True, 'sources': show_sources})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


if __name__ == "__main__":
    from werkzeug.serving import run_simple

    # Le port admin n'écoute qu'en 127.0.0.1 : il n'est jamais exposé sur le
    # réseau, avec ou sans pare-feu. Depuis une machine distante, on y accède
    # via un tunnel SSH : ssh -L <admin-port>:localhost:<admin-port> user@serveur
    # puis http://localhost:<admin-port>/admin/login dans le navigateur local.
    # Les deux ports servent la MÊME app Flask dans le même process (mêmes
    # PIPELINES/generator en mémoire, pas de désynchronisation entre "deux
    # serveurs") — seul le port d'écoute diffère. admin_routes.py vérifie en
    # plus que les requêtes /admin/* arrivent bien par ce port (voir
    # ADMIN_PORT dans runtime.py), au cas où le port public serait un jour
    # ouvert par erreur sur autre chose que 0.0.0.0 restreint.
    runtime.ADMIN_PORT = args.admin_port

    admin_thread = threading.Thread(
        target=lambda: run_simple("127.0.0.1", args.admin_port, app, threaded=True),
        daemon=True,
    )
    admin_thread.start()
    print(f"🔒 Back-office admin (local uniquement) : http://127.0.0.1:{args.admin_port}/admin/login")
    print(f"🌍 API publique (widget) : http://{args.host}:{args.port}/ask")

    run_simple(args.host, args.port, app, threaded=True)
