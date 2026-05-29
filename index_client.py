"""
Indexation d'un client spécifique sans démarrer le serveur.

Usage :
  python index_client.py --list
  python index_client.py --key sk-corte-tourisme-demo
  python index_client.py --key sk-corte-tourisme-demo --mode docs --reset
  python index_client.py --key sk-corte-tourisme-demo --mode web  --reset
  python index_client.py --key local --mode both --reset
"""
import argparse
from clients import CLIENTS, LOCAL
from legal_rag.pipeline import IngestionPipeline

parser = argparse.ArgumentParser(description="Ré-indexation d'un corpus client")
parser.add_argument("--key",   help="Clé API du client (ou 'local')")
parser.add_argument("--mode",  default="both", choices=["docs", "web", "both"],
                    help="docs = PDF/XML/JSON, web = sources web, both = tout (défaut)")
parser.add_argument("--reset", action="store_true", help="Supprimer et ré-indexer")
parser.add_argument("--list",  action="store_true", help="Lister les clients disponibles")
args = parser.parse_args()

if args.list:
    print("\n📋 Clients configurés :")
    for key, cfg in CLIENTS.items():
        web = ", ".join(cfg.get("web_sources", [])) or "—"
        print(f"  {cfg['name']:<25} clé: {key}")
        print(f"    corpus : {cfg['corpus']}")
        print(f"    web    : {web}")
    print(f"\n  {'local':<25} clé: local")
    print(f"    corpus : {LOCAL['corpus']}")
    print()

elif args.key:
    if args.key == "local":
        cfg = LOCAL
        name = "local"
    elif args.key in CLIENTS:
        cfg = CLIENTS[args.key]
        name = cfg["name"]
    else:
        print(f"❌ Clé inconnue : {args.key}")
        print("   Utilisez --list pour voir les clients disponibles")
        exit(1)

    print(f"\n🗂️  Indexation : {name}  [mode={args.mode}  reset={args.reset}]")
    p = IngestionPipeline(
        collection_name=cfg["collection"],
        retriever_type="recursive"
    )
    p.ingest_corpus(
        cfg["corpus"],
        force=args.reset,
        web_sources=cfg.get("web_sources", []),
        mode=args.mode
    )
    print(f"\n✅ Terminé : {name}")

else:
    parser.print_help()
