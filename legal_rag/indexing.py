from typing import List, Dict, Any, Optional
import ollama
from .models import LegalDocumentMetadata
from .config import chroma_client, EMBED_MODEL

class ContextualEnricher:
    """Enrichissement contextuel des chunks."""
    
    @staticmethod
    def enrich_chunk(
        chunk_text: str,
        metadata: LegalDocumentMetadata,
        chunk_type: str = "unknown"
    ) -> str:
        """
        Ajout d'un préfixe contextuel au chunk.
        
        Format: [Référence | Dispositif | Type de section]
        """
        context_parts = []
        
        # 1. Référence complète (le plus important)
        if metadata.reference_complete:
            context_parts.append(metadata.reference_complete)
        elif metadata.juridiction:
            ref = metadata.juridiction
            if metadata.date_decision:
                ref += f", {metadata.date_decision}"
            if metadata.numero_pourvoi:
                ref += f", n° {metadata.numero_pourvoi}"
            context_parts.append(ref)
        
        # 2. Dispositif (très discriminant)
        if metadata.dispositif:
            context_parts.append(f"Dispositif: {metadata.dispositif}")
        
        # 3. Type de section (optionnel, contexte additionnel)
        if chunk_type not in ['unknown', 'recursive', 'full_document']:
            context_parts.append(f"Section: {chunk_type}")
        
        # Assemblage
        if context_parts:
            prefix = "[" + " | ".join(context_parts) + "]"
            return f"{prefix}\n\n{chunk_text}"
        
        return chunk_text


class LegalCorpusIndexer:
    """
    Indexation dans ChromaDB avec embeddings Ollama (nomic-embed-text).
    """
    
    def __init__(self, collection_name: str = "legal_corpus_v1"):
        self.collection_name = collection_name
        self.collection = self._init_collection()
        self.enricher = ContextualEnricher()
    
    def _init_collection(self):
        """Initialisation collection ChromaDB."""
        try:
            # Note: En prod on ne delete pas systématiquement
            # chroma_client.delete_collection(self.collection_name)
            pass
        except:
            pass
        
        collection = chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Corpus juridique français - Master 2 TP"}
        )
        
        return collection
    
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Génération embeddings via Ollama (local, gratuit).

        Modèle: nomic-embed-text (768 dims, multilingue)
        """
        print(f"     🧠 Embedding {len(texts)} chunks...")

        try:
            response = ollama.embed(model=EMBED_MODEL, input=texts)
            embeddings = response.embeddings
            print(f"    ✅ {len(embeddings)} embeddings générés")
            return embeddings

        except Exception as e:
            print(f"    ❌ Erreur embedding: {e}")
            raise
    
    def index_document(
        self,
        chunks: List[Dict[str, Any]],
        enrich: bool = True
    ):
        """
        Indexation d'un document chunké dans ChromaDB.
        
        Args:
            chunks: Liste de {text, metadata, chunk_type, chunk_index}
            enrich: Appliquer enrichissement contextuel
        """
        if not chunks:
            print("  ⚠️ Aucun chunk à indexer")
            return
        
        print(f"   📥 Indexation de {len(chunks)} chunks...")
        
        # 1. Enrichissement
        if enrich:
            enriched_texts = [
                self.enricher.enrich_chunk(
                    c['text'],
                    c['metadata'],
                    c.get('chunk_type', 'unknown')
                )
                for c in chunks
            ]
        else:
            enriched_texts = [c['text'] for c in chunks]
        
        # 2. Filtrage des chunks vides/trop courts
        valid_chunks = []
        valid_texts = []
        for i, text in enumerate(enriched_texts):
            if len(text.strip()) >= 50:  # Minimum 50 caractères
                valid_chunks.append(chunks[i])
                valid_texts.append(text)
        
        if not valid_texts:
            print("  ⚠️ Tous les chunks filtrés (trop courts)")
            return
        
        print(f"    → {len(valid_texts)} chunks après filtrage")
        
        # 3. Génération embeddings
        embeddings = self.generate_embeddings(valid_texts)
        
        # 4. Préparation métadonnées ChromaDB
        chunk_metadatas = []
        for i, chunk in enumerate(valid_chunks):
            meta = chunk['metadata'].to_chromadb_metadata()
            meta['chunk_index'] = str(chunk['chunk_index'])
            meta['chunk_type'] = chunk.get('chunk_type', 'unknown')
            meta['chunk_total'] = str(len(valid_chunks))
            chunk_metadatas.append(meta)
        
        # 5. Génération IDs uniques
        doc_id = valid_chunks[0]['metadata'].document_id
        chunk_ids = [
            f"{doc_id}_chunk_{i}"
            for i in range(len(valid_chunks))
        ]
        
        # 6. Insertion ChromaDB
        self.collection.add(
            ids=chunk_ids,
            embeddings=embeddings,
            documents=valid_texts,
            metadatas=chunk_metadatas
        )
        
        print(f"  ✅ {len(valid_chunks)} chunks indexés")
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        filters: Optional[Dict] = None
    ) -> Dict:
        """
        Recherche hybride dans le corpus.
        """
        print(f"\n🔍 Recherche: '{query}'")
        if filters:
            print(f"   Filtres: {filters}")
        
        # Embedding de la requête
        query_embedding = self.generate_embeddings([query])[0]
        
        # Recherche ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=filters
        )
        
        print(f"   ✅ {len(results['ids'][0])} résultats")
        
        return results
