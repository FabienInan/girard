"""
MODULE 4 : SÉQUENÇAGE & AUTO-APPRENTISSAGE
Agent Commercial Autonome
=============================================================================
Objectif : gérer les relances multi-touch et la boucle de feedback
pour améliorer le RAG de M3 en continu.

State machine de relance :
  Jour 0   → message initial envoyé
  Jour +3  → pas de réponse → Relance 1 (angle différent)
  Jour +7  → pas de réponse → Relance 2 (valeur + preuve sociale)
  Jour +14 → pas de réponse → Relance 3 (breakup email)
  Réponse reçue → intent detection Ollama → "interested" | "not_now" |
                  "not_relevant" | "unsubscribe"

Boucle d'auto-apprentissage :
  Si intent == "interested" → persist (signal, message, réponse) dans ChromaDB
  → Le run suivant dans ce secteur bénéficie du pattern de succès

Output : runs/sequences.jsonl (schéma SequenceState dans core/schemas.py)
=============================================================================
"""

# TODO: implémenter le séquenceur et la boucle d'auto-apprentissage
