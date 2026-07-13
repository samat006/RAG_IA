"""
Indexation d'un client spécifique sans démarrer le serveur.
Source de vérité : admin.db (store.py) — les clients créés depuis le
back-office /admin sont donc visibles ici aussi, pas seulement ceux du
seed initial clients.py.

Usage :
  python index_client.py --list
  python index_client.py --key sk-corte-tourisme-demo
  python index_client.py --key sk-corte-tourisme-demo --mode docs --reset
  python index_client.py --key sk-corte-tourisme-demo --mode web  --reset
  python index_client.py --key local --mode both --reset
"""
import argparse
import store
from legal_rag import config
from legal_rag.pipeline import IngestionPipeline

store.init_db()
config.sync_from_store()

parser = argparse.ArgumentParser(description="Ré-indexation d'un corpus client")
parser.add_argument("--key",   help="Clé API du client (ou 'local')")
parser.add_argument("--mode",  default="both", choices=["docs", "web", "both"],
                    help="docs = PDF/XML/JSON, web = sources web, both = tout (défaut)")
parser.add_argument("--reset", action="store_true", help="Supprimer et ré-indexer")
parser.add_argument("--list",  action="store_true", help="Lister les clients disponibles")
args = parser.parse_args()

if args.list:
    print("\n📋 Clients configurés (admin.db) :")
    for cfg in store.list_clients():
        urls = store.list_url_strings(cfg["key"])
        print(f"  {cfg['name']:<25} clé: {cfg['key']}")
        print(f"    corpus : {cfg['corpus_dir']}")
        print(f"    web    : {', '.join(urls) or '—'}")
    print()

elif args.key:
    cfg = store.get_client(args.key)
    if cfg is None:
        print(f"❌ Clé inconnue : {args.key}")
        print("   Utilisez --list pour voir les clients disponibles")
        raise SystemExit(1)

    print(f"\n🗂️  Indexation : {cfg['name']}  [mode={args.mode}  reset={args.reset}]")
    p = IngestionPipeline(
        collection_name=cfg["collection"],
        retriever_type="recursive"
    )
    p.ingest_corpus(
        cfg["corpus_dir"],
        force=args.reset,
        web_sources=store.list_url_strings(args.key),
        mode=args.mode
    )
    print(f"\n✅ Terminé : {cfg['name']}")

else:
    parser.print_help()
