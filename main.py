import argparse
import os
from typing import Dict
from legal_rag.pipeline import LegalIngestionPipeline
from legal_rag.generation import LegalAnswerGenerator
from legal_rag.ragas import evaluate_rag 

# Couleurs ANSI
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text):
    print(f"\n{Colors.HEADER}{'='*80}{Colors.ENDC}")
    print(f"{Colors.BOLD} {text} {Colors.ENDC}")
    print(f"{Colors.HEADER}{'='*80}{Colors.ENDC}\n")

def print_section(text):
    print(f"\n{Colors.BLUE}{'-'*40}{Colors.ENDC}")
    print(f"{Colors.CYAN}👉 {text}{Colors.ENDC}")
    print(f"{Colors.BLUE}{'-'*40}{Colors.ENDC}")

def display_results(results: Dict):
    """Affichage formaté des résultats de recherche."""
    if not results or not results['ids'] or not results['ids'][0]:
        print(f"{Colors.WARNING}  Aucun résultat{Colors.ENDC}")
        return
    
    for i, (doc_id, document, distance, metadata) in enumerate(
        zip(
            results['ids'][0],
            results['documents'][0],
            results['distances'][0],
            results['metadatas'][0]
        ),
        start=1
    ):
        print(f"\n📄 {Colors.BOLD}Résultat {i}:{Colors.ENDC}")
        print(f"   ID: {doc_id}")
        # Gérer le cas où distance est None (parent retriever)
        dist_str = f"{distance:.4f}" if distance is not None else "N/A"
        print(f"   Distance: {dist_str}")
        print(f"   Référence: {Colors.GREEN}{metadata.get('reference_complete', 'N/A')}{Colors.ENDC}")
        print(f"   Dispositif: {metadata.get('dispositif', 'N/A')}")
        print(f"   Type: {metadata.get('chunk_type', 'N/A')}")
        print(f"   Extrait: {document[:200]}...")


def main():
    """
    Script principal avec CLI.
    """
    parser = argparse.ArgumentParser(description="- Data Ingestion Pipeline")
    parser.add_argument("--retriever", choices=["recursive", "parent-child"], default="recursive", help="Type de retriever à utiliser")
    parser.add_argument("--corpus", default="./documents"
    "/test", help="Chemin vers le dossier de documents")
    
    args = parser.parse_args()
    
    print_header("🏛️ DATA INGESTION PIPELINE")
    print(f"    Mode: {Colors.BOLD}{args.retriever.upper()}{Colors.ENDC}")
    
    # Initialisation du pipeline
    pipeline = LegalIngestionPipeline(
        collection_name="legal_corpus",
        retriever_type=args.retriever
    )
    
    # Initialisation du générateur
    generator = LegalAnswerGenerator()
    
    # Ingestion
    if not os.path.exists(args.corpus):
        print(f"{Colors.FAIL}❌ Créez le répertoire '{args.corpus}' et placez-y vos documents{Colors.ENDC}")
        return
    
    print_section(f"INGESTION DU CORPUS ({args.retriever.upper()})")
    pipeline.ingest_corpus(args.corpus)
    
    # TESTS DE RECHERCHE
    print_header("🔍 TESTS DE RECHERCHE & GÉNÉRATION")
    
    queries = [
       # "quels sont les lieux pour faire de LE BERCEAU DU SPORT NATURE",
        "quel sont les endroit INCONTOURNABLES a visiter ?",

   #"Des six citadelles corses, elle est la seule construite à l’intérieur des terres."
    #"Il est né de la volonté de la Collectivité Territoriale de Corse de doter l’île d’un équipement culturel de haut niveau. "

  #"Quel texte juridique permet à la Cour de cassation de déclarer ce pourvoi irrecevable ?",
      #  "pourvoi formé par M. X"
      #  "Quel article dit nul ne peut se pourvoir en cassation contre une décision à laquelle il n’a pas été partie ?"
    ]
    context="Arrêt Cass. 2e civ., 12 octobre 1989, n° 89-61.262 La Cour de cassation, deuxième chambre civile, a statué le 12 octobre 1989 sur un pourvoi formé par M. Gérard Z, résidant à Ucciani (Corse). Le pourvoi visait un jugement du tribunal d’instance d’Ajaccio rendu le 11 mars 1989 en matière électorale, favorable à Mme X Y épouse A, résidant à Ajaccio."

    
    for q in queries:
        print_section(f"Test: '{q}'")
        
        # 1. Retrieval
        results = pipeline.search(query=q, n_results=10 )
        display_results(results)
        
        # 2. Generation
        answer = generator.generate_answer(q, results)
        print(f"\n{Colors.BOLD}🤖 RÉPONSE GÉNÉRÉE :{Colors.ENDC}")
        print(f"{Colors.GREEN}{answer}{Colors.ENDC}")
        print("-" * 20)
       # evaluate_rag(q,answer,context)
    print_header("✅ TP TERMINÉ")


if __name__ == "__main__":
    main()
