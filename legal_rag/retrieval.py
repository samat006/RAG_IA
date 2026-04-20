from typing import List, Dict, Any
from .config import chroma_client
from .indexing import LegalCorpusIndexer

class ParentDocumentRetriever:
    """
     Implémentation du Parent Document Retriever.
    
    Principe:
    - Petits chunks (enfants) → Indexés pour recherche précise (vectorielle)
    - Gros chunks (parents) → Stockés pour contexte LLM (retrieval by ID)
    - Mapping enfant → parent via métadonnées
    
    Cette approche résout le "Trilemme du Chunking" :
    1. Précision de la recherche (petits vecteurs denses)
    2. Richesse du contexte (gros blocs de texte)
    3. Coût/Latence (on n'indexe que les petits chunks)
    """
    
    def __init__(self, collection_name_children: str, collection_name_parents: str):
        # Collection pour la recherche vectorielle (petits chunks)
        self.children_collection = chroma_client.get_or_create_collection(
            name=collection_name_children,
            metadata={"description": "Enfants (petits chunks) pour recherche vectorielle"}
        )
        
        # Collection pour le stockage de contenu (gros chunks)
        # Note: On pourrait utiliser une simple DB Key-Value (Redis, SQL) ici
        # car on ne fait pas de recherche vectorielle sur les parents.
        # Mais pour simplifier le TP, on utilise ChromaDB comme Key-Value store.
        self.parents_collection = chroma_client.get_or_create_collection(
            name=collection_name_parents,
            metadata={"description": "Parents (gros chunks) pour contexte"}
        )
        
        self.indexer = LegalCorpusIndexer(collection_name=collection_name_children)

    def index_with_hierarchy(
        self,
        parent_chunks: List[Dict[str, Any]],
        child_chunks: List[Dict[str, Any]]
    ):
        """
        Indexation hiérarchique: petits chunks indexés, gros chunks stockés.
        """
        print(f"  👨‍👧 Indexation Parent-Enfant: {len(parent_chunks)} parents, {len(child_chunks)} enfants")
        
        # 1. Stockage des Parents (Gros chunks)
        # On n'a pas besoin d'embeddings pour les parents, juste stockage ID -> Texte
        parent_ids = [f"parent_{c['metadata'].document_id}_{i}" for i, c in enumerate(parent_chunks)]
        parent_texts = [c['text'] for c in parent_chunks]
        parent_metadatas = [c['metadata'].to_chromadb_metadata() for c in parent_chunks]
        
        # On ajoute les parents (sans embeddings si possible pour économiser, 
        # mais Chroma calcule par défaut si absent. Ici on laisse Chroma gérer).
        self.parents_collection.add(
            ids=parent_ids,
            documents=parent_texts,
            metadatas=parent_metadatas
        )
        
        # 2. Indexation des Enfants (Petits chunks)
        # Il faut lier chaque enfant à son parent.
        # Stratégie simplifiée pour le TP: 
        # On suppose que child_chunks a une métadonnée 'parent_index' ou on fait un mapping positionnel.
        # Pour faire simple ici: on va découper chaque parent en enfants à la volée si ce n'est pas déjà fait.
        
        # Si les chunks enfants sont déjà fournis et liés:
        child_ids = []
        child_texts = []
        child_metadatas = []
        
        for i, child in enumerate(child_chunks):
            # On enrichit les métadonnées de l'enfant avec l'ID du parent
            # Hypothèse: child['parent_index'] existe et pointe vers l'index dans parent_chunks
            p_idx = child.get('parent_index', 0) 
            if p_idx < len(parent_ids):
                parent_id = parent_ids[p_idx]
                
                meta = child['metadata'].to_chromadb_metadata()
                meta['parent_id'] = parent_id # LIEN CRITIQUE
                meta['chunk_type'] = 'child'
                
                child_ids.append(f"child_{child['metadata'].document_id}_{i}")
                child_texts.append(child['text'])
                child_metadatas.append(meta)
        
        # Génération des embeddings pour les enfants (c'est eux qu'on cherche)
        if child_texts:
            embeddings = self.indexer.generate_embeddings(child_texts)
            
            self.children_collection.add(
                ids=child_ids,
                embeddings=embeddings,
                documents=child_texts,
                metadatas=child_metadatas
            )
            
        print(f"  ✅ Hiérarchie indexée: {len(parent_ids)} parents stockés, {len(child_ids)} enfants vectorisés")

    def retrieve_with_parent(self, query: str, n_results: int = 6) -> Dict:
        """
        1. Recherche sur petits chunks (précision)
        2. Récupération des parents (contexte)
        3. Retour des parents au LLM
        """
        print(f"\n🔍 Recherche Parent-Enfant: '{query}'")
        
        # 1. Recherche vectorielle sur les enfants
        query_embedding = self.indexer.generate_embeddings([query])[0]
        
        child_results = self.children_collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        
        if not child_results['ids'][0]:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        # 2. Récupération des IDs parents uniques
        parent_ids_to_fetch = []
        seen_parents = set()
        
        # On garde l'ordre de pertinence des enfants
        for meta in child_results['metadatas'][0]:
            p_id = meta.get('parent_id')
            if p_id and p_id not in seen_parents:
                parent_ids_to_fetch.append(p_id)
                seen_parents.add(p_id)
        
        if not parent_ids_to_fetch:
            print("  ⚠️ Aucun parent trouvé dans les métadonnées des enfants")
            return child_results # Fallback sur les enfants
            
        # 3. Fetch des documents parents
        print(f"  🔄 Récupération de {len(parent_ids_to_fetch)} documents parents...")
        parent_docs = self.parents_collection.get(
            ids=parent_ids_to_fetch
        )
        
        # Sécurité : Filtrer les None si jamais un ID manque
        valid_results = []
        if parent_docs['ids']:
             for pid, pdoc, pmeta in zip(parent_docs['ids'], parent_docs['documents'], parent_docs['metadatas']):
                 if pdoc: # Si le document existe bien
                     valid_results.append((pid, pdoc, pmeta))
        
        # Reconstitution des résultats (on renvoie les parents à la place des enfants)
        # Attention: l'ordre de .get() n'est pas garanti, il faut re-trier selon l'ordre de découverte
        parent_map = {item[0]: item[1] for item in valid_results}
        parent_meta_map = {item[0]: item[2] for item in valid_results}
        
        final_docs = []
        final_metadatas = []
        final_ids = []
        
        for p_id in parent_ids_to_fetch:
            if p_id in parent_map:
                final_docs.append(parent_map[p_id])
                final_metadatas.append(parent_meta_map[p_id])
                final_ids.append(p_id)
        
        # On structure comme un résultat Chroma standard pour compatibilité
        return {
            'ids': [final_ids],
            'documents': [final_docs],
            'metadatas': [final_metadatas],
            'distances': [child_results['distances'][0][:len(final_ids)]] # Approx
        }
