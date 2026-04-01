"""
Routeur LLM : sélectionne Ollama (local) ou Claude (cloud) selon la tâche.

Stratégie cible :
  ~80% des appels → Ollama + Mistral 7B (classification, scoring, intent)
  ~20% des appels → Claude Haiku (ICP, rédaction emails, validation complexe)
"""

# TODO: implémenter le routeur hybride Ollama / Claude
