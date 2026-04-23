"""
Script de test pour explorer la base ChromaDB :
  - Lister les collections
  - Extraire un document précis par ID ou par source_file
  - Faire des requêtes de similarité sur le corpus
"""

import chromadb
from chromadb.config import Settings
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from legal_rag.config import chroma_client, EMBED_MODEL
from legal_rag.indexing import LegalCorpusIndexer

SEPARATOR = "=" * 70


# ─── 1. LISTER LES COLLECTIONS ────────────────────────────────────────────────

def list_collections():
    print(f"\n{SEPARATOR}")
    print("COLLECTIONS DISPONIBLES")
    print(SEPARATOR)
    collections = chroma_client.list_collections()
    if not collections:
        print("  ⚠️  Aucune collection trouvée. La base est peut-être vide.")
        return []
    for col in collections:
        count = chroma_client.get_collection(col.name).count()
        print(f"  • {col.name:<45}  ({count} chunks)")
    return [col.name for col in collections]


# ─── 2. EXTRAIRE UN DOCUMENT PRÉCIS ───────────────────────────────────────────

def get_document_by_source(collection_name: str, source_file: str, max_chunks: int = 5):
    """Récupère tous les chunks d'un fichier source."""
    print(f"\n{SEPARATOR}")
    print(f"DOCUMENT : {source_file}")
    print(f"Collection: {collection_name}")
    print(SEPARATOR)

    col = chroma_client.get_collection(collection_name)
    results = col.get(
        where={"source_file": {"$contains": source_file}},
        limit=max_chunks,
        include=["documents", "metadatas"]
    )

    if not results["ids"]:
        print(f"  ⚠️  Aucun chunk trouvé pour source_file contenant '{source_file}'")
        return

    print(f"  {len(results['ids'])} chunk(s) trouvé(s) (affichage limité à {max_chunks})\n")
    for i, (doc_id, doc, meta) in enumerate(zip(results["ids"], results["documents"], results["metadatas"])):
        print(f"  --- Chunk {i+1} | ID: {doc_id} ---")
        print(f"  Métadonnées : {meta}")
        print(f"  Contenu     :\n{doc[:500]}{'...' if len(doc) > 500 else ''}")
        print()


def get_document_by_id(collection_name: str, doc_id: str):
    """Récupère un chunk précis par son ID ChromaDB."""
    print(f"\n{SEPARATOR}")
    print(f"CHUNK ID : {doc_id}")
    print(SEPARATOR)

    col = chroma_client.get_collection(collection_name)
    results = col.get(ids=[doc_id], include=["documents", "metadatas"])

    if not results["ids"]:
        print(f"  ⚠️  ID '{doc_id}' introuvable dans '{collection_name}'")
        return

    print(f"  Métadonnées : {results['metadatas'][0]}")
    print(f"  Contenu     :\n{results['documents'][0]}")


# ─── 3. REQUÊTES DE SIMILARITÉ ────────────────────────────────────────────────

def search_collection(collection_name: str, query: str, n_results: int = 5, max_distance: float = 1.2):
    """Recherche vectorielle dans une collection avec filtre de distance."""
    print(f"\n{SEPARATOR}")
    print(f"RECHERCHE : '{query}'")
    print(f"Collection: {collection_name}  |  top-{n_results}  |  distance ≤ {max_distance}")
    print(SEPARATOR)

    indexer = LegalCorpusIndexer(collection_name=collection_name)
    results = indexer.search(query, n_results=n_results)

    if not results["ids"][0]:
        print("  ⚠️  Aucun résultat.")
        return

    for i, (doc_id, doc, meta, dist) in enumerate(zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    )):
        if dist > max_distance:
            print(f"  [{i+1}] Ignoré (distance={dist:.4f} > {max_distance})")
            continue
        print(f"  [{i+1}] Distance: {dist:.4f}  |  ID: {doc_id}")
        print(f"       Source   : {meta.get('source_file', 'N/A')}")
        print(f"       Contenu  : {doc[:300]}{'...' if len(doc) > 300 else ''}")
        print()


# ─── 4. APERÇU GÉNÉRAL D'UNE COLLECTION ──────────────────────────────────────

def preview_collection(collection_name: str, n: int = 3):
    """Affiche les n premiers chunks d'une collection."""
    print(f"\n{SEPARATOR}")
    print(f"APERÇU : {collection_name} (premiers {n} chunks)")
    print(SEPARATOR)

    col = chroma_client.get_collection(collection_name)
    results = col.get(limit=n, include=["documents", "metadatas"])

    for i, (doc_id, doc, meta) in enumerate(zip(results["ids"], results["documents"], results["metadatas"])):
        print(f"  --- Chunk {i+1} | ID: {doc_id} ---")
        print(f"  Métadonnées : {meta}")
        print(f"  Contenu     : {doc[:400]}{'...' if len(doc) > 400 else ''}")
        print()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # 1. Lister toutes les collections
    col_names = list_collections()

    if not col_names:
        sys.exit(0)

    # 2. Choisir la collection principale (modifie si besoin)
    TARGET_COLLECTION = col_names[0]
    print(f"\n  >> Collection sélectionnée : {TARGET_COLLECTION}")

    # 3. Aperçu des premiers chunks
    preview_collection(TARGET_COLLECTION, n=3)

    # 4. Extraire un document précis par nom de fichier source
    #    Modifie 'mon_fichier' par une partie du nom de ton fichier
    get_document_by_source(TARGET_COLLECTION, source_file="Guide 2026 Partie 1", max_chunks=3)

    # 5. Requêtes de similarité — modifie les questions selon ton domaine
    questions = [
        "quel sont les pont INCONTOURNABLES a visiter sur corse?",
  
    ]

    for q in questions:
        search_collection(TARGET_COLLECTION, query=q, n_results=5, max_distance=1.2)


    queries = [
            "qui a creer le pont du Vechju ?",
            "parle moi de LE VENACAIS",
        "quel est le tarif d'une chambre double a l'hotel arena ?",
        # "quels sont les lieux pour faire de LE BERCEAU DU SPORT NATURE",
        #  "quel sont les endroit INCONTOURNABLES a visiter ?",
        # "le coffee cortenais ?"
    #"Des six citadelles corses, elle est la seule construite à l’intérieur des terres."
        #"Il est né de la volonté de la Collectivité Territoriale de Corse de doter l’île d’un équipement culturel de haut niveau. "

    #"Quel texte juridique permet à la Cour de cassation de déclarer ce pourvoi irrecevable ?",
        #  "pourvoi formé par M. X"
        #  "Quel article dit nul ne peut se pourvoir en cassation contre une décision à laquelle il n’a pas été partie ?"
    ]

        
    for q in queries:
            print_section(f"Test: '{q}'")
            
            # 1. Retrieval
            results = pipeline.search(query=q, n_results=5 )
            display_results(results)
            
            # 2. Generation
            answer = generator.generate_answer(q, results)
            print(f"\n{Colors.BOLD}🤖 RÉPONSE GÉNÉRÉE :{Colors.ENDC}")
            print(f"{Colors.GREEN}{answer}{Colors.ENDC}")
            print("-" * 20)
        # evaluate_rag(q,answer,context)
    print_header("✅ TP TERMINÉ")
