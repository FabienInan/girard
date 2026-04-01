"""
Wrapper ChromaDB pour la mémoire vectorielle du pipeline.
=============================================================================
Collection principale : "successful_messages"
Embeddings           : SentenceTransformers "all-MiniLM-L6-v2" (local, ~50ms)

Interface publique :
  add(message, metadata)        — persist un message réussi
  query(text, filters, top_k)   — RAG lookup par similarité + filtres metadata
  filter(metadata_filters)      — requête par metadata seuls (sans embedding)

Utilisé par :
  M3 (personalization_agent) — lookup des messages passés réussis
  M4 (sequencer)             — persist des nouveaux succès
=============================================================================
"""

# TODO: implémenter le wrapper ChromaDB
