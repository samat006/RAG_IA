from typing import List, Dict, Any, Optional
import re
import ollama
from .models import DocumentMetadata
from .config import chroma_client, EMBED_MODEL, MAX_CHUNK_SIZE

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
    
    @staticmethod
    def _clean_for_embedding(text: str) -> str:
        """Retire les balises Markdown avant embedding — améliore l'alignement sémantique."""
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\*{1,3}', '', text)
        text = re.sub(r'_{1,2}', '', text)
        text = re.sub(r'-{3,}', '\n', text)
        text = re.sub(r'\[.*?\]\(.*?\)', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Génération embeddings via Ollama (local, gratuit).
        Le texte est nettoyé du Markdown avant embedding.
        Modèle: nomic-embed-text (768 dims, multilingue)
        """
        print(f"     🧠 Embedding {len(texts)} chunks...")

        clean_texts = [self._clean_for_embedding(t) for t in texts]

        # Embed chunk par chunk pour éviter le dépassement du context length
        embeddings = []
        for i, text in enumerate(clean_texts):
            # Tronquer si trop long (nomic-embed-text : ~8192 tokens ≈ 6000 chars)
            if len(text) > MAX_CHUNK_SIZE:
                text = text[:MAX_CHUNK_SIZE]
            try:
                response = ollama.embed(model=EMBED_MODEL, input=[text])
                embeddings.append(response.embeddings[0])
            except Exception as e:
                print(f"    ❌ Erreur embedding chunk {i+1}: {e}")
                raise

        print(f"    ✅ {len(embeddings)} embeddings générés")
        return embeddings
    
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
    
    @staticmethod
    def _extract_keywords(query: str) -> List[str]:
        """
        Extrait les mots-clés importants d'une query pour la recherche par mot exact.
        Retourne les séquences de mots en majuscules et les noms propres (> 4 chars).
        """
        import re as _re
        # Séquences de mots commençant par une majuscule ou entièrement en majuscules
        tokens = _re.findall(r'\b[A-ZÀÂÄÉÈÊËÎÏÔÙÛÜ][A-ZÀÂÄÉÈÊËÎÏÔÙÛÜa-zàâäéèêëîïôùûü]+\b', query)
        # Filtre les mots trop courts et les mots fonctionnels
        stopwords = {'Quel','Quelle','Quels','Tarif','Prix','Chambre','Double','Hôtel','Hotel','HOTEL','HÔTEL'}
        keywords = [t for t in tokens if len(t) >= 4 and t not in stopwords]
        return keywords[:3]  # max 3 mots-clés

    def search(
        self,
        query: str,
        n_results: int = 5,
        filters: Optional[Dict] = None
    ) -> Dict:
        """
        Recherche hybride : dense (sémantique) + keyword exact.
        Les chunks qui contiennent les mots-clés exacts de la query
        sont ajoutés aux résultats vectoriels et dédoublonnés.
        """
        print(f"\n🔍 Recherche: '{query}'")

        # 1. Recherche vectorielle dense
        query_embedding = self.generate_embeddings([query])[0]
        query_kwargs: Dict = {"query_embeddings": [query_embedding], "n_results": n_results}
        if filters:
            query_kwargs["where"] = filters
        dense_results = self.collection.query(**query_kwargs)

        # 2. Recherche par mots-clés (keyword exact) — booste les entités nommées
        keywords = self._extract_keywords(query)
        keyword_docs, keyword_metas, keyword_ids = [], [], []
        seen_ids = set(dense_results['ids'][0])

        for kw in keywords:
            try:
                kw_res = self.collection.get(
                    where_document={"$contains": kw},
                    limit=3
                )
                for kid, kdoc, kmeta in zip(kw_res['ids'], kw_res['documents'], kw_res['metadatas']):
                    if kid not in seen_ids:
                        keyword_ids.append(kid)
                        keyword_docs.append(kdoc)
                        keyword_metas.append(kmeta)
                        seen_ids.add(kid)
            except Exception:
                pass

        # 3. Fusionner : résultats vectoriels d'abord, puis les keyword-only
        merged_ids  = dense_results['ids'][0]       + keyword_ids
        merged_docs = dense_results['documents'][0]  + keyword_docs
        merged_metas= dense_results['metadatas'][0]  + keyword_metas
        merged_dists= dense_results['distances'][0]  + [0.5] * len(keyword_ids)

        print(f"   ✅ {len(dense_results['ids'][0])} dense + {len(keyword_ids)} keyword = {len(merged_ids)} total")

        return {
            'ids':       [merged_ids],
            'documents': [merged_docs],
            'metadatas': [merged_metas],
            'distances': [merged_dists],
        }
