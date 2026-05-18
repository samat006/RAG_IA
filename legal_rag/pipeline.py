import os
import uuid
from pathlib import Path
from typing import Optional, Dict

from .models import DocumentMetadata
from .loaders import PDFLoader, XMLLoader, JSONLoader
from .chunkers import StructuralChunker, MarkdownChunker
from .indexing import CorpusIndexer
from .retrieval import ParentDocumentRetriever
from .config import DOMAIN, chroma_client, USE_OCR, PDF_MODE, WEB_SOURCES, WEB_MODE, WEB_FALLBACK_THRESHOLD
from .web_loader import WebLoader

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

class IngestionPipeline:
    """
    Pipeline complet d'ingestion pour tout type de corpus.
    """

    def __init__(self, collection_name: str = "legal_corpus_m2_tp", retriever_type: str = "recursive"):
        self.retriever_type = retriever_type
        self.collection_name = collection_name

        # Modes qui produisent du Markdown structuré → MarkdownChunker (découpe sur ##)
        if PDF_MODE in ("docling", "markdown"):
            self.chunker = MarkdownChunker(max_chunk_size=2000, min_chunk_size=100, overlap=0)
        else:
            self.chunker = StructuralChunker(max_chunk_size=1500, min_chunk_size=300, overlap=400)

        if self.retriever_type == "parent-child":
            self.parent_retriever = ParentDocumentRetriever(
                collection_name_children=f"{collection_name}_children",
                collection_name_parents=f"{collection_name}_parents"
            )
        else:
            self.indexer = CorpusIndexer(collection_name=collection_name)

    def ingest_document(self, file_path: str, doc_type: str, dump_text: bool = False):
        """Méthode générique d'ingestion."""
        
        # 1. Loading (Factory pattern simplifié)
        if doc_type == 'pdf':
            loader = PDFLoader(file_path, use_ocr=USE_OCR, pdf_mode=PDF_MODE)
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

        if dump_text and raw_text:
            dump_path = Path(file_path).with_suffix('.extracted.txt')
            dump_path.write_text(raw_text, encoding='utf-8')
            print(f"  💾 Texte sauvegardé : {dump_path}")
        
        # 2. Métadonnées
        if doc_type == 'pdf':
            metadata = DocumentMetadata(
                document_id=f"{meta_key}_{Path(file_path).stem}_{uuid.uuid4().hex[:8]}",
                source_file=loader_output['metadata']['source_file'],
                source_type=meta_key,
                domain=DOMAIN,
            )
        elif doc_type == 'xml':
             metadata = DocumentMetadata(
                document_id=f"{meta_key}_{Path(file_path).stem}_{uuid.uuid4().hex[:8]}",
                source_file=loader_output['source_file'],
                source_type=meta_key,
                domain=DOMAIN,
                juridiction=loader_output['metadata'].get('juridiction'),
                date_decision=loader_output['metadata'].get('date'),
                numero_pourvoi=loader_output['metadata'].get('numero'),
                reference_complete=loader_output['metadata'].get('reference'),
                type_document='ordonnance'
            )
        elif doc_type == 'json':
             metadata = DocumentMetadata(
                document_id=f"{meta_key}_{Path(file_path).stem}_{uuid.uuid4().hex[:8]}",
                source_file=loader_output['metadata']['source_file'],
                source_type=meta_key,
                domain=DOMAIN,
                date_decision=loader_output['metadata'].get('date'),
                type_document='document_json'
            )

        # 3. Chunking & Indexation selon stratégie
        if self.retriever_type == "parent-child":
            # Paramètres OPTIMISÉS — match avec chunking principal
            PARENT_SIZE = 2500    # ✅ FIXED: 2000 → 2500 (larger context windows)
            CHILD_SIZE = 800      # ✅ FIXED: 400 → 800 (denser search units)
            CHILD_OVERLAP = 200   # ✅ FIXED: 100 → 200 (better phrase preservation)

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
            self.indexer.index_document(chunks, enrich=False)

    def _collection_has_docs(self) -> bool:
        """Vérifie si la collection principale contient déjà des documents."""
        try:
            if self.retriever_type == "parent-child":
                count = self.parent_retriever.children_collection.count()
            else:
                count = self.indexer.collection.count()
            return count > 0
        except Exception:
            return False

    def ingest_corpus(self, corpus_dir: str, force: bool = False, dump_text: bool = False):
        """Ingestion récursive. Ignorée si la collection est déjà peuplée (sauf force=True)."""
        corpus_path = Path(corpus_dir)
        if not corpus_path.exists():
            print(f"❌ Répertoire introuvable: {corpus_dir}")
            return

        if force and self._collection_has_docs():
            print(f"\n🗑️  Reset demandé — suppression des collections existantes...")
            for name in [
                self.collection_name,
                f"{self.collection_name}_children",
                f"{self.collection_name}_parents",
            ]:
                try:
                    chroma_client.delete_collection(name)
                    print(f"   ✓ {name} supprimée")
                except Exception:
                    pass
            # Recréer les indexers/retrievers après suppression
            if self.retriever_type == "parent-child":
                self.parent_retriever = ParentDocumentRetriever(
                    collection_name_children=f"{self.collection_name}_children",
                    collection_name_parents=f"{self.collection_name}_parents",
                )
            else:
                self.indexer = CorpusIndexer(collection_name=self.collection_name)

        elif not force and self._collection_has_docs():
            if self.retriever_type == "parent-child":
                count = self.parent_retriever.children_collection.count()
            else:
                count = self.indexer.collection.count()
            print(f"\n✅ Collection '{self.collection_name}' déjà peuplée ({count} chunks) — ingestion ignorée.")
            print(f"   (Relancez avec --reset pour forcer la ré-indexation)")
            return

        print(f"\n🗂️  INGESTION DU CORPUS ({self.retriever_type.upper()}): {corpus_dir}")

        # 1. Documents locaux (PDF, XML, JSON)
        files = list(corpus_path.glob("**/*.*"))
        for f in files:
            try:
                if f.suffix == '.pdf':
                    self.ingest_document(str(f), 'pdf', dump_text=dump_text)
                elif f.suffix == '.xml':
                    self.ingest_document(str(f), 'xml', dump_text=dump_text)
                elif f.suffix == '.json':
                    self.ingest_document(str(f), 'json', dump_text=dump_text)
            except Exception as e:
                print(f"❌ Erreur sur {f.name}: {e}")

        # 2. Sources web (si configurées)
        if WEB_SOURCES:
            self.ingest_web_sources(WEB_SOURCES)

    def ingest_web_sources(self, urls: list):
        """Scrape et indexe les sources web configurées dans WEB_SOURCES."""
        print(f"\n🌐 INGESTION WEB ({len(urls)} site(s))")
        for base_url in urls:
            loader = WebLoader(base_url, max_pages=50)
            documents = loader.load_all()
            for doc in documents:
                raw_text = doc["raw_text"]
                metadata = doc["metadata"]
                chunks = self.chunker.chunk_document(raw_text, metadata)
                if self.retriever_type != "parent-child":
                    self.indexer.index_document(chunks, enrich=False)

    def search(self, query: str, n_results: int = 5, filters: Optional[Dict] = None):
        """
        Recherche selon WEB_MODE :
        - "separate" : cherche d'abord dans les documents locaux.
                       Si aucun résultat sous le seuil → bascule sur le web.
        - "mixed"    : fusionne directement les résultats docs + web.
        Cite toujours la source dans les métadonnées.
        """
        if self.retriever_type == "parent-child":
            return self.parent_retriever.retrieve_with_parent(query, n_results)

        if WEB_MODE == "separate":
            return self._search_separate(query, n_results)
        else:
            return self._search_separate(query, n_results)

    def _search_separate(self, query: str, n_results: int) -> dict:
        """
        Mode séparé :
        1. Cherche uniquement dans les documents locaux (source_type != web).
        2. Si le meilleur résultat dépasse WEB_FALLBACK_THRESHOLD → bascule web.
        3. Toujours inclure la source dans les métadonnées.
        """
        # Étape 1 — documents locaux uniquement
        doc_results = self.indexer.search(
            query, n_results,
            filters={"source_type": {"$in": ["pdf", "xml", "json"]}}
        )

        distances = doc_results.get("distances", [[]])[0]
        best_dist = min(distances) if distances else 999

        if best_dist <= WEB_FALLBACK_THRESHOLD:
            print(f"   📄 Réponse depuis les documents (dist={best_dist:.3f})")
            return doc_results

        # Étape 2 — fallback web
        print(f"   🌐 Pas de document pertinent (dist={best_dist:.3f} > {WEB_FALLBACK_THRESHOLD}) → recherche web")
        web_results = self.indexer.search(
            query, n_results,
            filters={"source_type": "web"}
        )
        return web_results