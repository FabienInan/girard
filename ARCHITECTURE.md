# Architecture — Agent Commercial Autonome v2

> **Stack** : Python 3.11+ · LangGraph · ChromaDB · Ollama (local) · Claude API (sparingly) · Zyte API  
> **Principe** : Ollama par défaut pour tout ce qui est classification/scoring. Claude API uniquement pour ICP generation et rédaction de messages (qualité critique). ~80% des appels LLM restent en local.

---

## Table des matières

1. [Vue d'ensemble du pipeline](#1-vue-densemble-du-pipeline)
2. [Stack technologique](#2-stack-technologique)
3. [Règle de routage LLM](#3-règle-de-routage-llm)
4. [Module 1 — Recherche et qualification](#4-module-1--recherche-et-qualification)
5. [Module 2 — Enrichissement contact](#5-module-2--enrichissement-contact)
6. [Module 3 — Agent de personnalisation](#6-module-3--agent-de-personnalisation)
7. [Module 4 — Séquençage et auto-apprentissage](#7-module-4--séquençage-et-auto-apprentissage)
8. [Boucle d'auto-apprentissage](#8-boucle-dauto-apprentissage)
9. [Structure des fichiers](#9-structure-des-fichiers)
10. [Variables d'environnement](#10-variables-denvironnement)
11. [Schéma de données](#11-schéma-de-données)
12. [Décisions d'architecture](#12-décisions-darchitecture)

---

## 1. Vue d'ensemble du pipeline

```
Phrase humaine libre
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  MODULE 1 — Recherche & qualification         ✅ BUILT    │
│                                                           │
│  ICP generation  ──►  SERP Zyte  ──►  Validation         │
│  (Claude API)         (Google)        (Claude + cache)    │
│                                            │              │
│                                       JSONL + ChromaDB    │
└───────────────────────────────────────────────────────────┘
        │  prospects.jsonl
        ▼
┌───────────────────────────────────────────────────────────┐
│  MODULE 2 — Enrichissement contact           🔲 TODO      │
│                                                           │
│  Site web scrape  ──►  Hunter / Apollo  ──►  LinkedIn     │
│  (Ollama classify)     (API)                (Zyte)        │
└───────────────────────────────────────────────────────────┘
        │  contacts.jsonl
        ▼
┌───────────────────────────────────────────────────────────┐
│  MODULE 3 — Agent de personnalisation    🔲 TODO  ★       │
│                                                           │
│  RAG lookup  ──►  Génération  ──►  Score & select         │
│  (ChromaDB)       (Claude API)    (Ollama local)          │
│                                                           │
│  ↻  Réponse reçue → signal → ChromaDB → amélioration      │
└───────────────────────────────────────────────────────────┘
        │  messages.jsonl
        ▼
┌───────────────────────────────────────────────────────────┐
│  MODULE 4 — Séquençage & auto-apprentissage  🔲 TODO      │
│                                                           │
│  LangGraph state  ──►  Intent detect  ──►  CRM push       │
│  (relances J0/3/7)     (Ollama local)     (HubSpot)       │
│                                                           │
│  ↻  Taux de réponse → enrichit ChromaDB                   │
└───────────────────────────────────────────────────────────┘
        │
        ▼
    Deal signé
```

---

## 2. Stack technologique

| Couche | Technologie | Version min | Rôle |
|---|---|---|---|
| LLM local | Ollama + Mistral 7B | `0.2.0` | Classification, scoring, intent detection |
| LLM local alt. | Ollama + Qwen 2.5 | — | Alternative plus légère à Mistral |
| LLM cloud | Claude Haiku (Anthropic) | `0.28.0` | ICP generation, rédaction emails |
| Agent | LangGraph | `0.1.0` | Orchestration stateful, cycles d'itération |
| LLM framework | LangChain + langchain-anthropic | `0.2.0` | Abstraction LLM, prompt management |
| Mémoire vectorielle | ChromaDB (local) | `0.5.0` | RAG, patterns réussis, historique |
| Embeddings | SentenceTransformers | `3.0.0` | Local, sans appel API externe |
| Scraping | Zyte API | `0.6.0` | SERP Google, sites web, LinkedIn |
| Parsing HTML | BeautifulSoup4 | `4.12.0` | Extraction texte depuis HTML |
| Enrichissement | Hunter.io / Apollo | API externe | Email professionnel du décideur |
| CRM | HubSpot / Notion | API externe | Push final des prospects convertis |
| Validation | Pydantic v2 | `2.7.0` | Schémas stricts sur toutes les sorties LLM |
| Config | python-dotenv | `1.0.0` | Clés API via `.env` |
| Async | asyncio + aiofiles | stdlib | Concurrence, persistance crash-safe |

### Installation

```bash
pip install -r requirements.txt

# Ollama (séparé de pip)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull mistral      # 4.1 GB — recommandé
ollama pull qwen2.5      # alternative plus légère
```

---

## 3. Règle de routage LLM

Avant d'ajouter un appel LLM, appliquer cette règle :

```
La tâche nécessite-t-elle un raisonnement complexe
ou une créativité linguistique de haute qualité ?
        │
       OUI ──► Claude API (Haiku)
        │        · Génération d'ICP depuis phrase brute
        │        · Rédaction du cold email / InMail
        │        · Cas edge où Ollama est incertain (score < 0.7)
        │
        NO  ──► Ollama local (Mistral 7B)
                 · Classification secteur / géographie
                 · Pré-filtrage des URLs
                 · Scoring des variantes de messages (0-100)
                 · Détection d'intention dans les réponses
                 · Extraction d'entités (nom, email, titre)
```

**Résultat attendu** : ~80% des appels LLM en local, Claude API sur ~20%.  
**Économie estimée** : 10-15x moins cher qu'une architecture 100% cloud.

---

## 4. Module 1 — Recherche et qualification

**Statut** : ✅ Opérationnel — fichier `modules/m1_prospect_finder.py`

### Pipeline interne

```
Phrase brute
    │
    ▼  Claude Haiku
generate_icp()
    → ICPProfile (Pydantic, 11 dimensions)
    → sub_sectors[] utilisé à l'étape suivante
    │
    ▼  Claude Haiku
generate_search_queries(sub_sectors)
    → 2 dorks × N sous-secteurs (max 10 requêtes)
    → diversité sectorielle garantie
    │
    ▼  Zyte SERP API — asyncio.gather (parallèle)
search_google() × N requêtes
    → ~10 URLs par requête, ~100 URLs brutes total
    │
    ▼  filter_and_deduplicate_urls()        ← mis à jour
    [1] Filtre EXCLUDED_DOMAINS
    [2] Dédup par domaine RACINE
        www.co.qc.ca + blog.co.qc.ca → co.qc.ca (1 URL)
    [3] Scoring par chemin d'URL
        /a-propos /equipe  → score 2  ✦ priorité haute
        /contact           → score 1
        /                  → score 0
        /blog /emplois     → score -1 ✗ exclus
    [4] Tri décroissant par score
        → pages /a-propos validées en premier
    [5] Cap à max_urls (défaut 100)
    → ~60-70 URLs candidates triées par qualité
    │
    ▼  _build_validation_system_msg()  [1 seule fois par run]
    → SystemMessage avec cache_control (ephemeral)
    → ICP + offer_type + few-shots > 1024 tokens
    → cache Haiku actif dès le 2e appel (~90% économie input)
    │
    ▼  asyncio.Semaphore(3) — max 3 validations en parallèle
validate_prospect_website() × N URLs
    ├── _fetch_url()
    │     httpResponseBody (rapide) → fallback browserHtml si < 500 chars
    ├── BeautifulSoup → strip scripts/nav/footer → texte[:8000]
    └── Claude Haiku + cache → ProspectValid | ProspectInvalid
    │
    ▼  asyncio.Lock (self._file_lock — instancié une fois dans __init__)
_persist_prospect()
    → append immédiat runs/prospects.jsonl (crash-safe)
    │
    ▼
Rapport : N prospects | $X.XXXXX | cache X% tokens input
```

### Optimisations actives

| Optimisation | Détail |
|---|---|
| Dorks par sous-secteur | 2 dorks × N sous-secteurs ICP (max 10) → diversité sectorielle, évite la sur-représentation d'un secteur |
| Dédup domaine racine | `www.co.qc.ca` = `blog.co.qc.ca` = `co.qc.ca` → zéro doublon inter-sous-domaines |
| Scoring URL | Chemin `/a-propos`, `/equipe` prioritaires (score 2) ; `/blog`, `/emplois` exclus (score -1) avant appel Claude |
| Tri par score | Les URLs les plus qualifiantes passent en premier → si run interrompu, les meilleurs prospects sont déjà sauvegardés |
| Prompt caching | `_SYSTEM_VALIDATION` > 1024 tokens (few-shots) → cache Haiku actif, ~90% économie tokens input dès le 2e appel |
| Fetch adaptatif | `httpResponseBody` d'abord (rapide + pas cher), fallback `browserHtml` si body < 500 chars |
| Semaphore | Max 3 validations concurrentes (rate limit Zyte + Anthropic) |
| asyncio.Lock | Instancié une fois dans `__init__`, partagé entre coroutines → écriture JSONL thread-safe |
| TokenTracker | Coût USD estimé loggé à chaque fin de run |

### Estimation des coûts (Claude Haiku)

| Étape | Appels | Coût estimé |
|---|---|---|
| `generate_icp()` | 1 | ~$0.003 |
| `generate_search_queries()` | 1 | ~$0.001 |
| `validate()` × 20 URLs | 20 (1 cache write + 19 reads) | ~$0.015 |
| `validate()` × 50 URLs | 50 (1 cache write + 49 reads) | ~$0.025 |
| **Run typique 20 URLs** | | **~$0.04–0.06** |
| **Run typique 50 URLs** | | **~$0.08–0.10** |

### Évolution prévue : pré-filtre Ollama

```python
async def _prefilter_ollama(self, url: str, text: str, icp: str) -> float:
    """
    Score 0.0-1.0 via Ollama local.
    Si score < 0.7 → abandon, pas d'appel Claude.
    Si score >= 0.7 → validation complète Claude.
    Réduit les appels Claude de ~30%.
    """
```

---

## 5. Module 2 — Enrichissement contact

**Statut** : 🔲 À construire

### Objectif

À partir de chaque `ProspectValid` (M1), trouver :
- Nom et titre du décideur principal
- Email professionnel vérifié
- Profil LinkedIn si disponible

### Pipeline interne — stratégie en cascade

```
URL validée (depuis prospects.jsonl)
    │
    ▼  Zyte + BeautifulSoup + Ollama classify
scrape_company_pages()
    ├── /equipe, /contact, /about, footer
    ├── Ollama décide si la page vaut le scraping (< 200ms)
    │
    ├── email trouvé ? ──► OUI ──► contacts.jsonl
    │
    ▼  NO → Hunter.io API
hunter_find_email()          → email par domaine + nom
    ├── email trouvé ? ──► OUI ──► contacts.jsonl
    │
    ▼  NO → LinkedIn via Zyte
linkedin_find_decision_maker() → profil décideur
    │
    ▼
contacts.jsonl
```

### Schéma de sortie

```python
class Contact(BaseModel):
    company_name: str
    company_url: str
    full_name: str
    title: str
    email: str
    email_confidence: float      # 0.0-1.0 (score Hunter)
    linkedin_url: Optional[str]
    source: str                  # "site" | "hunter" | "apollo" | "linkedin"
    found_at: str                # ISO datetime
```

---

## 6. Module 3 — Agent de personnalisation

**Statut** : 🔲 À construire · ★ Priorité haute

### Principe

Agent LangGraph avec mémoire RAG. Chaque message est généré en s'appuyant sur les patterns qui ont déjà généré des réponses dans le même secteur, avec le même type de signal.

Un email générique : 2-3% de réponse.  
Un email calibré sur des patterns RAG réels : 15-25% estimé.

### Graphe LangGraph

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AgentState(TypedDict):
    contact:          dict
    icp:              dict
    signals:          list[str]
    rag_patterns:     list[str]   # récupérés depuis ChromaDB
    variants:         list[str]   # générées par Claude
    scores:           list[float] # scorées par Ollama
    selected_message: str
    iteration:        int         # max 2

graph = StateGraph(AgentState)
graph.add_node("rag_lookup",        rag_lookup_node)
graph.add_node("generate_variants", generate_variants_node)
graph.add_node("score_and_select",  score_and_select_node)
graph.add_node("quality_gate",      quality_gate_node)

graph.set_entry_point("rag_lookup")
graph.add_edge("rag_lookup",        "generate_variants")
graph.add_edge("generate_variants", "score_and_select")
graph.add_edge("score_and_select",  "quality_gate")
graph.add_conditional_edges(
    "quality_gate",
    lambda s: "generate_variants"
              if s["iteration"] < 2 and s["scores"][0] < 70
              else END
)
```

### Description des nœuds

**Nœud 1 — `rag_lookup` (ChromaDB + SentenceTransformers)**

Requête vectorielle : `embedding(signal + secteur + offre)`.  
Retourne les 3 messages passés avec `reply_positive = True` les plus proches.  
Zéro appel API — SentenceTransformers tourne en local.

**Nœud 2 — `generate_variants` (Claude API)**

Seul appel Claude de tout le module.  
Input : contact + signals + rag_patterns.  
Output : 3 variantes de message (email ou InMail).  
Les patterns RAG sont injectés dans le prompt comme few-shots dynamiques.

**Nœud 3 — `score_and_select` (Ollama local)**

Score chaque variante sur 4 critères (0-25 chacun) :

| Critère | Ce qu'on vérifie |
|---|---|
| Personnalisation | Le signal prospect est-il ancré dans le message ? |
| Clarté | La proposition de valeur est-elle lisible en < 5 secondes ? |
| Appel à l'action | Le CTA est-il précis et simple ? |
| Longueur | Le message fait-il < 150 mots ? |

Score total sur 100. Seuil de sortie : 70.

**Nœud 4 — `quality_gate`**

Si score < 70 et `iteration < 2` → retour au nœud 2 avec feedback Ollama.  
Si score >= 70 ou `iteration == 2` → sortie.

### Structure ChromaDB

```python
# Collection : "successful_messages"
# Modèle d'embedding : SentenceTransformers("all-MiniLM-L6-v2")

collection.add(
    documents=[message_text],
    metadatas=[{
        "sector":         "BTP",
        "signal_type":    "recrutement",
        "offer_type":     "Service",
        "reply_received": True,
        "reply_positive": True,
        "sent_at":        "2026-03-15T10:00:00"
    }],
    ids=[f"msg_{uuid}"]
)

# Requête au moment de la génération (nœud 1)
results = collection.query(
    query_texts=[f"{signal} {sector} {offer_type}"],
    n_results=3,
    where={"reply_positive": True}
)
```

---

## 7. Module 4 — Séquençage et auto-apprentissage

**Statut** : 🔲 À construire

### Machine à états des relances

```
Message envoyé (J0)
    │
    ├── J+3 : pas de réponse ──► relance 1 (angle différent)
    ├── J+7 : pas de réponse ──► relance 2 (valeur + social proof)
    ├── J+14 : pas de réponse ──► relance 3 (breakup email)
    │
    └── Réponse reçue ──► intent_detection (Ollama)
              │
              ├── "interested"    → alerte commerciale + push CRM
              ├── "not_now"       → snooze 30 jours
              ├── "not_relevant"  → disqualification
              └── "unsubscribe"   → blacklist domaine
```

### Détection d'intention — Ollama

```python
INTENT_PROMPT = """
Classifie cette réponse email en exactement un mot parmi :
interested | not_now | not_relevant | unsubscribe

Réponse : {reply_text}

Retourne uniquement le mot, rien d'autre.
"""
# Modèle : Mistral 7B via Ollama
# Latence : < 300ms
# Aucun appel Claude nécessaire
```

### Feedback loop vers ChromaDB

Quand `intent == "interested"`, le triplet est persisté automatiquement :

```python
collection.add(
    documents=[message_sent],
    metadatas=[{
        "sector":         contact.sector,
        "signal_type":    prospect.signals[0],
        "offer_type":     icp.offer_type,
        "reply_received": True,
        "reply_positive": True,
    }]
)
# → enrichit le RAG du Module 3 pour tous les prochains runs
```

---

## 8. Boucle d'auto-apprentissage

```
Run 1 — ChromaDB vide
  └── RAG retourne 0 patterns
  └── Claude génère "à froid"
  └── Ollama score : 68/100 → 2e itération
  └── Message envoyé

        ↓  J+3 : réponse positive

  └── Triplet (signal, message, réponse) → ChromaDB

Run 2 — même secteur
  └── RAG retourne 1 pattern réel
  └── Claude s'en inspire
  └── Ollama score : 82/100 → sortie au 1er essai

        ↓  Après 50 réponses positives

Run N
  └── RAG retourne les 3 meilleurs patterns du secteur
  └── Messages calibrés sur de vraies réponses
  └── Taux de réponse estimé : 15-25%
```

Le système ne se fine-tune pas au sens ML (pas de gradient).  
Il apprend par **mémoire épisodique** : chaque succès devient un exemple récupérable par similarité vectorielle. C'est de l'apprentissage par renforcement implicite.

---

## 9. Structure des fichiers

```
agent-commercial/
│
├── .env                            # Clés API — jamais committé
├── .env.example                    # Template public
├── requirements.txt                # Dépendances Python
├── ARCHITECTURE.md                 # Ce fichier
│
├── modules/
│   ├── m1_prospect_finder.py       # ✅ Opérationnel (v4)
│   ├── m2_contact_enricher.py      # 🔲 À construire
│   ├── m3_personalization_agent.py # 🔲 À construire
│   └── m4_sequencer.py             # 🔲 À construire
│
├── core/
│   ├── llm_router.py               # 🔲 Logique routage Ollama vs Claude
│   ├── token_tracker.py            # Suivi coûts USD par run
│   ├── schemas.py                  # Tous les modèles Pydantic
│   └── utils.py                    # retry_async, parse_llm_json,
│                                   # extract_root_domain, score_url,
│                                   # filter_and_deduplicate_urls
│
├── memory/
│   ├── chroma_store.py             # Wrapper ChromaDB (read/write/query)
│   └── chroma_db/                  # Données vectorielles persistées (local)
│
├── runs/
│   ├── prospects.jsonl             # Sortie M1
│   ├── contacts.jsonl              # Sortie M2
│   ├── messages.jsonl              # Sortie M3
│   └── sequences.jsonl             # Sortie M4
│
└── main.py                         # Orchestrateur — entrée du pipeline complet
```

---

## 10. Variables d'environnement

```bash
# ── APIs cloud ────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
ZYTE_API_KEY=...
HUNTER_API_KEY=...           # ou APOLLO_API_KEY=...

# ── CRM (un seul requis) ──────────────────────────────────────
HUBSPOT_API_KEY=...
NOTION_API_KEY=...
NOTION_DATABASE_ID=...

# ── Ollama (local — pas de clé) ───────────────────────────────
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral         # ou qwen2.5

# ── ChromaDB (local par défaut) ───────────────────────────────
CHROMA_PERSIST_DIR=./memory/chroma_db

# ── Limites pipeline ──────────────────────────────────────────
MAX_URLS_PER_RUN=10
MAX_CONCURRENT_VALIDATIONS=3
MAX_MESSAGE_ITERATIONS=2
```

---

## 11. Schéma de données

### ICPProfile — M1 vers tous les modules

```python
class ICPProfile(BaseModel):
    sector: str
    sub_sectors: list[str]
    company_size: str
    geography: str
    decision_maker_title: list[str]
    offer_type: str                  # "Produit" | "Service"
    offer_description: str
    buying_signals: list[str]
    pain_points: list[str]
    icp_description: str             # paragraphe synthétique
    excluded_domains_extra: list[str]
```

### ProspectValid — M1 vers M2

```python
class ProspectValid(BaseModel):
    valid: bool
    company_name: str
    industry: str
    signals: list[str]
    fit_reason: str
    url: str
    saved_at: str
```

### Contact — M2 vers M3

```python
class Contact(BaseModel):
    company_name: str
    company_url: str
    full_name: str
    title: str
    email: str
    email_confidence: float
    linkedin_url: Optional[str]
    source: str                      # "site" | "hunter" | "apollo" | "linkedin"
    found_at: str
```

### MessageRecord — M3 vers M4

```python
class MessageRecord(BaseModel):
    contact_email: str
    company_name: str
    message_body: str
    channel: str                     # "email" | "linkedin" | "sms"
    rag_patterns_used: int
    ollama_score: float
    iterations_needed: int
    generated_at: str
```

### SequenceState — M4

```python
class SequenceState(BaseModel):
    message_record: MessageRecord
    status: str                      # "sent" | "replied" | "bounced" | "unsubscribed"
    intent: Optional[str]            # "interested" | "not_now" | "not_relevant" | "unsubscribe"
    followup_count: int
    next_action_at: Optional[str]
    crm_pushed: bool
    reply_text: Optional[str]
    closed_at: Optional[str]
```

---

## 12. Décisions d'architecture

### Pourquoi LangGraph plutôt qu'un simple script ?

Un script linéaire ne peut pas gérer les cycles d'itération (re-générer si score < 70), les machines à états des séquences (J0 → J3 → J7), ni la persistance de l'état en cas de crash. LangGraph fournit des checkpoints natifs, des edges conditionnels, et une observabilité du graphe.

### Pourquoi ChromaDB local plutôt qu'un service cloud ?

Les données de prospection sont sensibles (emails, noms, entreprises). Local = zéro transfert vers un tiers. La performance est suffisante pour les volumes cibles (< 100k documents). Migration vers Pinecone ou Qdrant Cloud triviale si le besoin de scale se présente.

### Pourquoi SentenceTransformers plutôt que l'API Embeddings d'Anthropic ou OpenAI ?

Les embeddings sont générés très fréquemment — chaque message entrant dans ChromaDB, chaque lookup RAG. À l'échelle, le coût d'une API d'embeddings devient significatif. `all-MiniLM-L6-v2` tourne en < 50ms sur CPU pour des textes courts comme des emails, sans aucun appel réseau.

### Pourquoi Haiku et pas Sonnet pour Claude ?

Haiku est 10x moins cher que Sonnet pour une qualité suffisante sur les tâches définies (ICP generation, email writing avec contexte RAG riche). Sonnet peut être activé ponctuellement si la qualité des messages est insuffisante sur un secteur spécifique via la variable `CLAUDE_MODEL` dans `.env`.

### Pourquoi JSONL plutôt qu'une base SQL ?

Chaque module produit un fichier JSONL (1 JSON par ligne, append-only). Crash-safe, inspectable avec `jq`, aucune migration de schéma pendant le développement. Migration vers SQLite ou PostgreSQL triviale quand le volume le justifiera.

### Pourquoi `asyncio.Lock` en attribut de classe ?

Instancier `asyncio.Lock()` dans une méthode async crée un nouveau verrou à chaque appel. En contexte concurrent (semaphore + gather), chaque coroutine a son propre lock indépendant → protection illusoire en écriture fichier. Le lock doit être instancié une seule fois dans `__init__` et partagé par toutes les coroutines de l'instance.

### Pourquoi le prompt caching uniquement sur `_SYSTEM_VALIDATION` ?

Claude Haiku exige un minimum de 1024 tokens dans le bloc annoté pour activer le cache. `_SYSTEM_ICP` et `_SYSTEM_DORKS` sont sous ce seuil et appelés une seule fois par run — annoter `cache_control` dessus est un no-op silencieux. Seul `_SYSTEM_VALIDATION` dépasse 1024 tokens (few-shots inclus) et est appelé N fois par run → c'est le seul endroit où le cache a un impact réel (économie ~90% des tokens input sur les validations).

---

*Document maintenu à jour à chaque nouveau module livré.*  
*Dernière mise à jour : 31 mars 2026 — M1 v4 : dorks par sous-secteur, dédup domaine racine, scoring URL*
