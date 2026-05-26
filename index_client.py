"""
Indexation d'un client spécifique sans démarrer le serveur.

Usage :
  python index_client.py --list
  python index_client.py --key sk-corte-tourisme-demo
  python index_client.py --key sk-corte-tourisme-demo --reset
"""
import argparse
from clients import CLIENTS, LOCAL
from legal_rag.pipeline import IngestionPipeline

parser = argparse.ArgumentParser()
parser.add_argument("--key",   help="Clé API du client à indexer")
parser.add_argument("--reset", action="store_true", help="Vider et ré-indexer")
parser.add_argument("--list",  action="store_true", help="Lister les clients")
args = parser.parse_args()

if args.list:
    print("\n📋 Clients configurés :")
    for key, cfg in CLIENTS.items():
        print(f"  {cfg['name']:<25} clé: {key}   corpus: {cfg['corpus']}")
    print(f"  {'local':<25} corpus: {LOCAL['corpus']}")
    print()

elif args.key:
    if args.key not in CLIENTS:
        print(f"❌ Clé inconnue : {args.key}")
        print("   Utilisez --list pour voir les clients disponibles")
        exit(1)

    cfg = CLIENTS[args.key]
    print(f"\n🗂️  Indexation : {cfg['name']}")
    p = IngestionPipeline(collection_name=cfg["collection"], retriever_type="recursive")
    p.ingest_corpus(cfg["corpus"], force=args.reset, web_sources=cfg.get("web_sources", []))

    print(f"\n✅ Terminé : {cfg['name']}")

else:
    parser.print_help()
