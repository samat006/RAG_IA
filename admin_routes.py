"""
Back-office admin (/admin/*) : gestion des clients, URLs, documents et réglages
RAG globaux (backend de génération, mode d'extraction PDF, seuil de distance...).

L'état partagé (pipelines par client, générateur) vit dans runtime.py, importé
normalement ici (PAS via un `import server` différé) : server.py est lancé en
`python server.py`, donc il s'exécute comme `__main__` et non comme un module
`server` — un `import server` depuis un autre fichier le réexécuterait depuis
zéro sous ce nom, créant un second PIPELINES déconnecté de celui réellement
utilisé par les routes actives. runtime.py ne dépend ni de server.py ni de
admin_routes.py, donc l'importer ici normalement est sans risque de cycle.
"""
import os
import shutil
import secrets
import threading
from functools import wraps
from pathlib import Path

from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename

import store
import runtime
from legal_rag import config

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ALLOWED_EXTENSIONS = {"pdf", "xml", "json"}
DOC_EXTENSIONS = {".pdf", ".xml", ".json"}


# ── Auth : mot de passe unique + session, CSRF minimal ─────────────────────
def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)
    return wrapped


def _get_csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@admin_bp.app_template_global()
def csrf_token():
    return _get_csrf_token()


@admin_bp.before_request
def _check_admin_port():
    """
    Défense en profondeur : /admin/* ne doit répondre que sur le port admin
    (voir server.py, qui le lie à 127.0.0.1 uniquement — jamais exposé sur le
    réseau). Si une requête /admin/* arrive quand même par le port public
    (ex. mauvaise config réseau future), on renvoie 404 comme si la route
    n'existait pas, plutôt que de laisser passer jusqu'au login.
    """
    if request.environ.get("SERVER_PORT") != str(runtime.ADMIN_PORT):
        return "Not Found", 404


@admin_bp.before_request
def _check_csrf():
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not token or not secrets.compare_digest(token, session.get("csrf", "")):
            return "Session expirée ou formulaire invalide — rechargez la page.", 400


# ── Helpers ─────────────────────────────────────────────────────────────────
def _list_documents(corpus_dir: str) -> list:
    p = Path(corpus_dir)
    if not p.exists():
        return []
    return sorted(
        [f.name for f in p.iterdir() if f.is_file() and f.suffix.lower() in DOC_EXTENSIONS]
    )


def _chunk_count(pipeline) -> "int | None":
    try:
        return pipeline.indexer.collection.count() if pipeline is not None else None
    except Exception:
        return None


# ── Auth routes ───────────────────────────────────────────────────────────
@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    _get_csrf_token()
    error = None
    if request.method == "POST":
        if not ADMIN_PASSWORD:
            error = "ADMIN_PASSWORD n'est pas configuré côté serveur (variable d'environnement manquante)."
        elif secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(url_for("admin.dashboard"))
        else:
            error = "Mot de passe incorrect."
    return render_template("admin_login.html", error=error)


@admin_bp.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("admin.login"))


# ── Dashboard ─────────────────────────────────────────────────────────────
@admin_bp.route("/")
@require_admin
def dashboard():
    rows = []
    for cfg in store.list_clients():
        pipeline = runtime.PIPELINES.get(cfg["key"])
        rows.append({
            **cfg,
            "doc_count": len(_list_documents(cfg["corpus_dir"])),
            "url_count": len(store.list_urls(cfg["key"])),
            "chunk_count": _chunk_count(pipeline),
        })
    return render_template("admin_dashboard.html", clients=rows, settings=store.get_settings())


# ── Réglages globaux ──────────────────────────────────────────────────────
@admin_bp.route("/settings", methods=["GET", "POST"])
@require_admin
def settings_view():
    error = None
    if request.method == "POST":
        try:
            store.update_settings(
                generation_backend=request.form.get("generation_backend", "mistral_api"),
                generation_model=request.form.get("generation_model", "").strip() or "mistral-small-latest",
                pdf_mode=request.form.get("pdf_mode", "docling"),
                web_mode=request.form.get("web_mode", "mixed"),
                max_distance=float(request.form.get("max_distance", 0.9)),
                web_fallback_threshold=float(request.form.get("web_fallback_threshold", 0.6)),
                n_results=int(request.form.get("n_results", 12)),
            )
        except ValueError:
            error = "Valeur numérique invalide pour le seuil de distance ou n_results."
        else:
            config.sync_from_store()
            runtime.reload_generator()
            return redirect(url_for("admin.settings_view"))
    return render_template(
        "admin_settings.html",
        settings=store.get_settings(),
        mistral_key_set=bool(config.MISTRAL_API_KEY),
        error=error,
    )


# ── Clients ───────────────────────────────────────────────────────────────
@admin_bp.route("/clients/new", methods=["POST"])
@require_admin
def new_client():
    name = request.form.get("name", "").strip()
    if not name:
        return "Le nom du client est obligatoire.", 400
    cfg = store.create_client(name)
    try:
        runtime.register_client_pipeline(cfg)
    except Exception as e:
        print(f"⚠️  Client {cfg['name']} créé mais pipeline en échec : {e}")
    return redirect(url_for("admin.client_detail", key=cfg["key"]))


@admin_bp.route("/clients/<key>")
@require_admin
def client_detail(key):
    cfg = store.get_client(key)
    if cfg is None:
        return "Client inconnu", 404
    return render_template(
        "admin_client.html",
        client=cfg,
        is_local=(key == "local"),
        urls=store.list_urls(key),
        documents=_list_documents(cfg["corpus_dir"]),
        chunk_count=_chunk_count(runtime.PIPELINES.get(key)),
    )


@admin_bp.route("/clients/<key>/delete", methods=["POST"])
@require_admin
def delete_client_view(key):
    cfg = store.get_client(key)
    if cfg is None:
        return "Client inconnu", 404
    if key == "local":
        return "Le client 'local' ne peut pas être supprimé.", 400

    runtime.PIPELINES.pop(key, None)

    if request.form.get("delete_collection") == "on":
        try:
            config.chroma_client.delete_collection(cfg["collection"])
        except Exception as e:
            print(f"⚠️  Suppression de la collection '{cfg['collection']}' échouée : {e}")

    if request.form.get("delete_files") == "on":
        shutil.rmtree(cfg["corpus_dir"], ignore_errors=True)

    store.delete_client(key)
    return redirect(url_for("admin.dashboard"))


# ── URLs ──────────────────────────────────────────────────────────────────
@admin_bp.route("/clients/<key>/urls", methods=["POST"])
@require_admin
def add_client_url(key):
    if store.get_client(key) is None:
        return "Client inconnu", 404
    url = request.form.get("url", "").strip()
    if url:
        store.add_url(key, url)
    return redirect(url_for("admin.client_detail", key=key))


@admin_bp.route("/clients/<key>/urls/<int:url_id>/delete", methods=["POST"])
@require_admin
def delete_client_url(key, url_id):
    if store.get_client(key) is None:
        return "Client inconnu", 404
    store.remove_url(url_id)
    return redirect(url_for("admin.client_detail", key=key))


# ── Documents ─────────────────────────────────────────────────────────────
@admin_bp.route("/clients/<key>/documents", methods=["POST"])
@require_admin
def upload_document(key):
    cfg = store.get_client(key)
    if cfg is None:
        return "Client inconnu", 404

    file = request.files.get("document")
    if file is None or not file.filename:
        return redirect(url_for("admin.client_detail", key=key))

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return "Type de fichier non autorisé (pdf, xml, json uniquement).", 400

    filename = secure_filename(file.filename)
    corpus_dir = Path(cfg["corpus_dir"])
    corpus_dir.mkdir(parents=True, exist_ok=True)
    dest = corpus_dir / filename
    file.save(dest)

    def run():
        pipeline = runtime.PIPELINES.get(key) or runtime.register_client_pipeline(cfg)
        # Ré-upload d'un fichier déjà indexé : on retire d'abord ses anciens
        # chunks, sinon ils s'accumulent (les IDs de chunk sont des UUID
        # aléatoires, donc ChromaDB ne déduplique rien tout seul).
        try:
            pipeline.indexer.collection.delete(where={"source_file": filename})
        except Exception:
            pass
        try:
            pipeline.ingest_document(str(dest), ext, dump_text=False)
            print(f"✅ Document indexé : {filename} ({cfg['name']})")
        except Exception as e:
            print(f"❌ Échec d'indexation de {filename} ({cfg['name']}) : {e}")

    threading.Thread(target=run, daemon=True).start()
    return redirect(url_for("admin.client_detail", key=key))


@admin_bp.route("/clients/<key>/documents/<path:filename>/delete", methods=["POST"])
@require_admin
def delete_document(key, filename):
    cfg = store.get_client(key)
    if cfg is None:
        return "Client inconnu", 404

    safe_name = secure_filename(filename)
    path = Path(cfg["corpus_dir"]) / safe_name
    if path.exists():
        path.unlink()

    pipeline = runtime.PIPELINES.get(key)
    if pipeline is not None:
        try:
            pipeline.indexer.collection.delete(where={"source_file": safe_name})
        except Exception as e:
            print(f"⚠️  Suppression des chunks échouée pour {safe_name} : {e}")

    return redirect(url_for("admin.client_detail", key=key))


@admin_bp.route("/clients/<key>/reindex", methods=["POST"])
@require_admin
def reindex_client(key):
    if store.get_client(key) is None:
        return "Client inconnu", 404
    mode = request.form.get("mode", "both")
    runtime.trigger_reindex(key, mode=mode, reset=True)
    return redirect(url_for("admin.client_detail", key=key))
