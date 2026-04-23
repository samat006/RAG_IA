from typing import List, Dict, Any, Optional
import ollama
from .models import DocumentMetadata
from .config import chroma_client, EMBED_MODEL

class ContextualEnricher:
    """Enrichissement contextuel des chunks."""
    
    @staticmethod
    def enrich_chunk(
        chunk_text: str,
        metadata: DocumentMetadata,
        chunk_type: str = "unknown"
    ) -> str:
        """
        Ajout d'un préfixe contextuel au chunk — uniquement si les métadonnées
        apportent une vraie information (pas de null inutiles).
        """
        from .config import DOMAIN
        context_parts = []

        # 1. Référence complète (documents juridiques uniquement)
        if DOMAIN not in ("tourisme", "municipal", "rh", "medical"):
            if metadata.reference_complete and metadata.reference_complete != "null":
                context_parts.append(metadata.reference_complete)
            elif metadata.juridiction and metadata.juridiction != "null":
                ref = metadata.juridiction
                if metadata.date_decision and metadata.date_decision != "null":
                    ref += f", {metadata.date_decision}"
                if metadata.numero_pourvoi and metadata.numero_pourvoi != "null":
                    ref += f", n° {metadata.numero_pourvoi}"
                context_parts.append(ref)

        # 2. Résultat/décision (uniquement si présent et non null)
        if metadata.dispositif and metadata.dispositif != "null":
            context_parts.append(f"Résultat: {metadata.dispositif}")

        # 3. Type de section (uniquement si informatif)
        meaningful_types = {'procedure', 'recevabilite', 'motifs', 'dispositif',
                            'historique', 'attractions', 'presentation'}
        if chunk_type in meaningful_types:
            context_parts.append(f"Section: {chunk_type}")

        # On n'ajoute le préfixe que s'il apporte vraiment du contexte
        if context_parts:
            prefix = "[" + " | ".join(context_parts) + "]"
            return f"{prefix}\n\n{chunk_text}"

        return chunk_text


class CorpusIndexer:
    """
    Indexation dans ChromaDB avec embeddings Ollama (nomic-embed-text).
    """

    def __init__(self, collection_name: str = "corpus_v1"):
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
            metadata={"description": "corpus de documents avec enrichissement contextuel"}
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
        
        # Recherche ChromaDB (ne pas passer where=None — bug ChromaDB sur certaines versions)
        query_kwargs: Dict = {"query_embeddings": [query_embedding], "n_results": n_results}
        if filters:
            query_kwargs["where"] = filters
        results = self.collection.query(**query_kwargs)
        
        print(f"   ✅ {len(results['ids'][0])} résultats")
        
        return results
