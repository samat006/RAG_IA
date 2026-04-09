import os
import uuid
from pathlib import Path
from typing import Optional, Dict

from .models import LegalDocumentMetadata
from .loaders import PDFLoader, XMLLoader, JSONLoader
from .extractors import LLMMetadataExtractor
from .chunkers import StructuralLegalChunker
from .indexing import LegalCorpusIndexer
from .retrieval import ParentDocumentRetriever

def sliding_window_splitter(text, chunk_size, overlap):
    """
    Découpe un texte en chunks avec chevauchement (overlap).
    Indispensable pour ne pas couper des phrases clés en deux.
    """
    chunks = []
    if not text:
        return chunks
    
    # Cas simple si le texte est plus petit que le chunk
    if len(text) <= chunk_size:
        return [text]
        
    start = 0
    while start < len(text):
        end = start + chunk_size
        # On ne coupe pas au milieu d'un mot si possible (amélioration optionnelle)
        # Ici version simple par caractère pour l'exemple
        chunk = text[start:end]
        chunks.append(chunk)
        
        # Avancée : on recule de 'overlap' pour le prochain chunk
        start += (chunk_size - overlap)
        
        # Sécurité boucle infinie
        if (chunk_size - overlap) <= 0:
            break
            
    return chunks

class LegalIngestionPipeline:
    """
    Pipeline complet d'ingestion pour corpus juridique.
    """
    
    def __init__(self, collection_name: str = "legal_corpus_tp", retriever_type: str = "recursive"):
        self.retriever_type = retriever_type
        self.collection_name = collection_name
        
        # Chunker standard
        self.chunker = StructuralLegalChunker(
            max_chunk_size=800,
            min_chunk_size=100,
            overlap=100
        )
        
        self.metadata_extractor = LLMMetadataExtractor()
        
        # Initialisation selon le type de retriever
        if self.retriever_type == "parent-child":
            self.parent_retriever = ParentDocumentRetriever(
                collection_name_children=f"{collection_name}_children",
                collection_name_parents=f"{collection_name}_parents"
            )
            # Note: Le chunker spécifique n'est plus utilisé ici, on utilise sliding_window_splitter
        else:
            self.indexer = LegalCorpusIndexer(collection_name=collection_name)

    def ingest_document(self, file_path: str, doc_type: str):
        """Méthode générique d'ingestion."""
        
        # 1. Loading (Factory pattern simplifié)
        if doc_type == 'pdf':
            loader = PDFLoader(file_path)
            meta_key = 'pdf'
        elif doc_type == 'xml':
            loader = XMLLoader(file_path)
            meta_key = 'xml'
        elif doc_type == 'json':
            loader = JSONLoader(file_path)
            meta_key = 'json'
        else:
            raise ValueError(f"Type non supporté: {doc_type}")
            
        loader_output = loader.load()
        raw_text = loader_output['raw_text']
        
        # 2. Métadonnées
        if doc_type == 'pdf':
             legal_meta = self.metadata_extractor.extract_legal_metadata(raw_text)
             metadata = LegalDocumentMetadata(
                document_id=f"{meta_key}_{Path(file_path).stem}_{uuid.uuid4().hex[:8]}",
                source_file=loader_output['metadata']['source_file'],
                source_type=meta_key,
                **legal_meta
            )
        elif doc_type == 'xml':
             metadata = LegalDocumentMetadata(
                document_id=f"{meta_key}_{Path(file_path).stem}_{uuid.uuid4().hex[:8]}",
                source_file=loader_output['source_file'],
                source_type=meta_key,
                juridiction=loader_output['metadata'].get('juridiction'),
                date_decision=loader_output['metadata'].get('date'),
                numero_pourvoi=loader_output['metadata'].get('numero'),
                reference_complete=loader_output['metadata'].get('reference'),
                type_document='ordonnance'
            )
        elif doc_type == 'json':
             metadata = LegalDocumentMetadata(
                document_id=f"{meta_key}_{Path(file_path).stem}_{uuid.uuid4().hex[:8]}",
                source_file=loader_output['metadata']['source_file'],
                source_type=meta_key,
                date_decision=loader_output['metadata'].get('date'),
                juridiction=loader_output['metadata'].get('juridiction'),
                type_document='audience_metadata'
            )

        # 3. Chunking & Indexation selon stratégie
        if self.retriever_type == "parent-child":
            # Paramètres OPTIMISÉS
            PARENT_SIZE = 2000
            CHILD_SIZE = 400
            CHILD_OVERLAP = 100

            parent_chunks = []
            child_chunks = []

            # 1. Création des PARENTS (Gros blocs)
            parent_texts = sliding_window_splitter(raw_text, PARENT_SIZE, 0)
            
            for p_index, p_text in enumerate(parent_texts):
                # Création de l'objet Parent
                parent_obj = {
                    "text": p_text,
                    "metadata": metadata, # On garde les métadonnées d'origine
                }
                
                # Position absolue du parent dans la liste locale pour le mapping
                # Note: Dans l'implémentation originale, on passait une liste globale, 
                # mais ici on traite document par document. 
                # ParentDocumentRetriever.index_with_hierarchy attend une liste de parents et d'enfants.
                # Il faudra s'assurer que l'indexation gère bien les IDs uniques.
                
                parent_chunks.append(parent_obj)
                
                # 2. Création des ENFANTS (Petits blocs DENSES)
                child_texts = sliding_window_splitter(p_text, CHILD_SIZE, CHILD_OVERLAP)
                
                for c_text in child_texts:
                    child_obj = {
                        "text": c_text,
                        "metadata": metadata,
                        "parent_index": p_index # Index relatif à la liste parent_chunks actuelle
                    }
                    child_chunks.append(child_obj)
            
            self.parent_retriever.index_with_hierarchy(parent_chunks, child_chunks)
            
        else:
            # Recursive standard
            chunks = self.chunker.chunk_document(raw_text, metadata)
            self.indexer.index_document(chunks, enrich=True)

    def ingest_corpus(self, corpus_dir: str):
        """Ingestion récursive."""
        corpus_path = Path(corpus_dir)
        if not corpus_path.exists():
            print(f"❌ Répertoire introuvable: {corpus_dir}")
            return
            
        print(f"\n🗂️  INGESTION DU CORPUS ({self.retriever_type.upper()}): {corpus_dir}")
        
        files = list(corpus_path.glob("**/*.*"))
        for f in files:
            try:
                if f.suffix == '.pdf':
                    self.ingest_document(str(f), 'pdf')
                elif f.suffix == '.xml':
                    self.ingest_document(str(f), 'xml')
                elif f.suffix == '.json':
                    self.ingest_document(str(f), 'json')
            except Exception as e:
                print(f"❌ Erreur sur {f.name}: {e}")

    def search(self, query: str, n_results: int = 3, filters: Optional[Dict] = None):
        """Recherche unifiée."""
        if self.retriever_type == "parent-child":
            # Note: filters non implémentés dans parent-child pour ce TP simple
            return self.parent_retriever.retrieve_with_parent(query, n_results)
        else:
            return self.indexer.search(query, n_results, filters)
