"""
MODULE 3 : AGENT DE PERSONNALISATION ★ PRIORITÉ HAUTE
Agent Commercial Autonome
=============================================================================
Objectif : générer des emails/InMail cold outreach personnalisés avec un
taux de réponse cible de 15-25% (vs 2-3% pour un email générique).

Architecture LangGraph (4 nœuds) :
  1. RAG Lookup    — ChromaDB : 3 messages passés réussis (secteur + signal + offre)
  2. Generate      — Claude Haiku : 3 variantes de message (few-shots = RAG)
  3. Score         — Ollama local : note chaque variante sur 4 critères (0-100)
                     Seuil : 70/100 pour passer la quality gate
  4. Quality Gate  — Si score < 70 et iterations < 2 → retour en step 2 avec feedback

ChromaDB collection : "successful_messages"
Embeddings         : SentenceTransformers "all-MiniLM-L6-v2" (local, 50ms/msg)

Output : runs/messages.jsonl (schéma MessageRecord dans core/schemas.py)
=============================================================================
"""

# TODO: implémenter l'agent de personnalisation (LangGraph + RAG ChromaDB)
