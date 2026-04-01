"""
MODULE 2 : ENRICHISSEMENT DES CONTACTS
Agent Commercial Autonome
=============================================================================
Objectif : à partir de chaque prospect validé (runs/prospects.jsonl),
extraire le décideur, son email et son LinkedIn.

Pipeline (cascade) :
  1. Scraping pages /team /contact /about /footer (Zyte + BeautifulSoup)
  2. Si email trouvé → sauvegarde dans runs/contacts.jsonl
  3. Sinon → Hunter.io API lookup
  4. Sinon → LinkedIn search via Zyte

Output : runs/contacts.jsonl (schéma Contact dans core/schemas.py)
=============================================================================
"""

# TODO: implémenter le module d'enrichissement des contacts
