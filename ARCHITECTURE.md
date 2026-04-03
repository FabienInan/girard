# Architecture — Agent Commercial Autonome v3

> **Stack** : Python 3.11+ · LangGraph · ChromaDB · Ollama Cloud · Zyte API
> **Principe** : 100% des appels LLM via Ollama Cloud (modèles open source hébergés). Coût marginal vs Claude API.

---

## Table des matières

1. [Vue d'ensemble du pipeline](#1-vue-densemble-du-pipeline)
2. [Stack technologique](#2-stack-technologique)
3. [Module 1 — Recherche et qualification](#4-module-1--recherche-et-qualification)
4. [Module 2 — Enrichissement contact](#5-module-2--enrichissement-contact)
5. [Module 3 — Agent de personnalisation](#6-module-3--agent-de-personnalisation)
6. [Module 4 — Séquençage et auto-apprentissage](#7-module-4--séquençage-et-auto-apprentissage)
7. [Structure des fichiers](#9-structure-des-fichiers)
8. [Variables d'environnement](#10-variables-denvironnement)
9. [Schéma de données](#11-schéma-de-données)
10. [Décisions d'architecture](#12-décisions-darchitecture)

---

## 1. Vue d'ensemble du pipeline

```
Phrase humaine libre (CLI ou interactif)
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  MODULE 1 — Recherche & qualification         ✅ BUILT    │
│                                                           │
│  ICP generation  ──►  SERP Zyte  ──►  Validation         │
│  (Ollama Cloud)       (Google)        (Ollama Cloud)       │
│        │                                                  │
│        └── Few-shots dynamiques (générés par le LLM)      │
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
│  (ChromaDB)       (Ollama Cloud)   (Ollama Cloud)         │
│                                                           │
│  ↻  Réponse reçue → signal → ChromaDB → amélioration      │
└───────────────────────────────────────────────────────────┘
        │  messages.jsonl
        ▼
┌───────────────────────────────────────────────────────────┐
│  MODULE 4 — Séquençage & auto-apprentissage  🔲 TODO      │
│                                                           │
│  LangGraph state  ──►  Intent detect  ──►  CRM push       │
│  (relances J0/3/7)     (Ollama Cloud)     (HubSpot)       │
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
| LLM cloud | Ollama Cloud | — | ICP generation, validation, rédaction emails |
| Modèles recommandés | `ministral-3:8b`, `gemma3:12b`, `gpt-oss:20b` | — | Modèles non-reasoning (éviter qwen3.5, deepseek) |
| Agent | LangGraph | `0.1.0` | Orchestration stateful, cycles d'itération |
| LLM framework | LangChain + langchain-ollama | — | Abstraction LLM, prompt management |
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

# Créer une clé API sur https://ollama.com/settings
# Configurer .env avec OLLAMA_API_KEY
```

---

## 3. Module 1 — Recherche et qualification

**Statut** : ✅ Opérationnel — fichier `modules/m1_prospect_finder.py`

### Pipeline interne

```
Phrase brute (CLI: --phrase "..." ou prompt interactif)
    │
    ▼  Ollama Cloud (ministral-3:8b)
generate_icp()
    → ICPProfile (Pydantic, 11 dimensions)
    → sub_sectors[] utilisé à l'étape suivante
    │
    ▼  Ollama Cloud
generate_few_shots()
    → 3 exemples de validation générés dynamiquement
    → adaptés à l'ICP spécifique du run
    │
    ▼  Ollama Cloud
generate_search_queries(sub_sectors)
    → 2 dorks × N sous-secteurs (max 10 requêtes)
    → diversité sectorielle garantie
    │
    ▼  Zyte SERP API — asyncio.gather (parallèle)
search_google() × N requêtes
    → ~10 URLs par requête, ~100 URLs brutes total
    │
    ▼  filter_and_deduplicate_urls()
    [1] Filtre EXCLUDED_DOMAINS
    [2] Dédup par domaine RACINE
    [3] Scoring par chemin d'URL
    [4] Tri décroissant par score
    [5] Cap à max_urls (défaut 80)
    │
    ▼  asyncio.Semaphore(3) — max 3 validations en parallèle
validate_prospect_website() × N URLs
    ├── _fetch_url() avec géolocalisation configurable
    ├── BeautifulSoup → strip scripts/nav/footer → texte[:3500]
    └── Ollama Cloud → ProspectValid | ProspectInvalid
    │
    ▼
prospects.jsonl (crash-safe append)
```

### Fonctionnalités v6 (actuelles)

| Fonctionnalité | Détail |
|---|---|
| Few-shots dynamiques | 3 exemples générés par le LLM à chaque run, adaptés à l'ICP |
| Géographie configurable | `extract_geo_code()` détecte FR, CA, US, etc. depuis l'ICP |
| CLI configurable | `--phrase`, `--target`, `--output` ou prompt interactif |
| Parallélisme | Semaphore(3) pour 3 validations concurrentes |
| Modèles Ollama Cloud | ministral-3:8b, gemma3:12b, gpt-oss:20b (éviter modèles "thinking") |
| Réparation JSON | `parse_llm_json()` répare automatiquement les JSON malformés (virgules manquantes, trailing commas, texte environnant) |

### Estimation des coûts (Ollama Cloud)

| Étape | Appels | Coût |
|---|---|---|
| `generate_icp()` | 1 | Variable selon modèle |
| `generate_few_shots()` | 1 | Variable selon modèle |
| `generate_search_queries()` | 1 | Variable selon modèle |
| `validate()` × 20 URLs | 20 | Variable selon modèle |

**Note** : Les modèles Ollama Cloud ont un quota gratuit horaire/hebdomadaire. Consulter https://ollama.com/settings pour les tarifs actuels.

---

## 4. Module 2 — Enrichissement contact

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
    ├── Ollama décide si la page vaut le scraping
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

---

## 5. Module 3 — Agent de personnalisation

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
    variants:         list[str]   # générées par Ollama
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

---

## 6. Module 4 — Séquençage et auto-apprentissage

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

---

## 7. Structure des fichiers

```
girard/
│
├── .env                            # Clés API — jamais committé
├── .env.example                    # Template public
├── requirements.txt                # Dépendances Python
├── ARCHITECTURE.md                 # Ce fichier
│
├── modules/
│   ├── m1_prospect_finder.py       # ✅ Opérationnel (v5)
│   ├── m2_contact_enricher.py      # 🔲 À construire
│   ├── m3_personalization_agent.py # 🔲 À construire
│   └── m4_sequencer.py             # 🔲 À construire
│
├── core/
│   ├── llm_router.py               # 🔲 Logique routage Ollama
│   ├── token_tracker.py            # Suivi tokens par run
│   ├── schemas.py                  # Tous les modèles Pydantic
│   └── utils.py                    # retry_async, parse_llm_json,
│                                   # extract_root_domain, score_url,
│                                   # filter_and_deduplicate_urls,
│                                   # extract_geo_code
│                                   # JSON auto-repair (v6)
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
└── main.py                         # Orchestrateur — entrée du pipeline
```

---

## 8. Variables d'environnement

```bash
# ── APIs cloud ────────────────────────────────────────────────
ZYTE_API_KEY=your_zyte_key
OLLAMA_API_KEY=your_ollama_api_key      # https://ollama.com/settings
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_MODEL=ministral-3:8b             # ou gemma3:12b, gpt-oss:20b

# ── CRM (un seul requis) ──────────────────────────────────────
HUBSPOT_API_KEY=...
NOTION_API_KEY=...
NOTION_DATABASE_ID=...

# ── ChromaDB (local par défaut) ───────────────────────────────
CHROMA_PERSIST_DIR=./memory/chroma_db

# ── Limites pipeline ──────────────────────────────────────────
MAX_URLS_PER_RUN=80
MAX_CONCURRENT_VALIDATIONS=3
MAX_MESSAGE_ITERATIONS=2
```

### Modèles Ollama Cloud disponibles

| Modèle | Recommandé pour | Taille |
|---|---|---|
| `ministral-3:8b` | Classification, validation | 8B |
| `gemma3:12b` | Génération ICP | 12B |
| `gpt-oss:20b` | Alternative | 20B |

**⚠️ Éviter** les modèles "thinking" (qwen3.5, deepseek) qui ne retournent pas le JSON directement.

---

## 9. Schéma de données

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

---

## 10. Décisions d'architecture

### Pourquoi Ollama Cloud au lieu de Claude API ?

1. **Coût marginal** : Les modèles open source hébergés coûtent une fraction du prix de Claude API.
2. **Modèles variés** : Accès à ministral, gemma, gpt-oss, etc.
3. **Quota gratuit** : Quota horaire/hebdomadaire inclus.
4. **Transparence** : Pas de verrouillage fournisseur.

### Pourquoi few-shots dynamiques ?

Les exemples hardcodés dans les prompts limitaient le système à un cas d'usage unique (logiciel de devis au Québec). Avec les few-shots dynamiques :
- Le système s'adapte à n'importe quel secteur/géographie
- Les exemples sont générés en fonction de l'ICP spécifique
- Meilleure qualité de validation

### Pourquoi géographie configurable ?

Le système devait supporter n'importe quelle zone géographique (FR, CA, US, etc.). La fonction `extract_geo_code()` détecte automatiquement le code pays depuis la description de l'ICP.

### Pourquoi Semaphore(3) et non séquentiel ?

Les appels à Ollama Cloud peuvent être parallélisés. Le semaphore à 3 permet de traiter 3 URLs simultanément sans surcharger l'API.

### Pourquoi JSONL plutôt qu'une base SQL ?

Chaque module produit un fichier JSONL (1 JSON par ligne, append-only). Crash-safe, inspectable avec `jq`, aucune migration de schéma pendant le développement. Migration vers SQLite ou PostgreSQL triviale quand le volume le justifiera.

### Pourquoi la réparation JSON automatique ?

Les LLM open source (ministral, gemma) génèrent parfois du JSON malformé : virgules manquantes, trailing commas, texte avant/après le JSON. La fonction `parse_llm_json()` tente plusieurs réparations avant d'échouer :
1. Parse direct
2. Suppression des trailing commas (`,]` → `]`)
3. Ajout des virgules manquantes entre objets (`} {` → `}, {`)
4. Extraction du JSON depuis le texte environnant

---

*Document maintenu à jour à chaque nouveau module livré.*
*Dernière mise à jour : 3 avril 2026 — v6 : JSON auto-repair, parallélisme Semaphore(3)*