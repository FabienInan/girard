"""
=============================================================================
MODULE 1 : RECHERCHE & QUALIFICATION DE PROSPECTS — v4
Agent Commercial Autonome — Brique Fondatrice
=============================================================================
Améliorations v3 :
  [1] offer_type transmis jusqu'à la validation (contexte métier complet)
  [2] Filtre de domaines exclus avant validation (pas de Wikipedia/LinkedIn)
  [3] Fetch adaptatif : httpResponseBody d'abord, browserHtml si vide
  [4] Déduplication par domaine (pas par URL exacte)
  [5] Ordre SERP préservé (les meilleurs résultats passent en premier)
  [6] Persistance temps réel (crash-safe, flush JSON à chaque prospect)
  [7] Génération des dorks via SystemMessage/HumanMessage + prompt caching
  [8] Tracking des coûts tokens (input / output / cache) par run

Optimisations cache v4 :
  [C1] PROBLÈME CORRIGÉ : aucun prompt n'atteignait le minimum de 1024 tokens
       requis par Anthropic pour activer le cache sur Haiku → cache_control
       était annoté mais ne déclenchait rien.
  [C2] _SYSTEM_VALIDATION enrichi de few-shots exemples → franchit les 1024
       tokens → cache s'active réellement.
  [C3] ICP + offer_type déplacés du user_message vers le system_message de
       validation (ils sont constants sur tout le run) → le bloc caché est
       identique byte-pour-byte sur les N appels de validation → cache hit
       garanti dès le 2ème appel.
  [C4] system_message de validation construit UNE SEULE FOIS dans run() et
       passé à chaque appel → garantie supplémentaire d'identité du bloc.
  [C5] asyncio.Lock() instancié en attribut de classe (self._file_lock)
       et non plus à chaque appel (chaque new Lock() est indépendant →
       protection illusoire en contexte concurrent).
  [C6] _SYSTEM_ICP et _SYSTEM_DORKS : appelés une seule fois par run,
       le cache ne profite qu'aux runs multiples (TTL 5 min). Conservé
       mais documenté comme "cross-run" uniquement.
=============================================================================
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from zyte_api import AsyncZyteAPI
from bs4 import BeautifulSoup
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import ValidationError
from dotenv import load_dotenv

from core.schemas import ICPProfile, ProspectValid, ProspectInvalid
from core.token_tracker import TokenTracker
from core.utils import EXCLUDED_DOMAINS, retry_async, parse_llm_json, filter_and_deduplicate_urls

# =============================================================================
# CONFIGURATION
# =============================================================================

load_dotenv()

ZYTE_API_KEY      = os.getenv("ZYTE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not ZYTE_API_KEY or not ANTHROPIC_API_KEY:
    raise EnvironmentError(
        "Variables manquantes dans .env : ZYTE_API_KEY et/ou ANTHROPIC_API_KEY"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# CLASSE PRINCIPALE
# =============================================================================

class ProspectFinder:

    # =========================================================================
    # PROMPTS STATIQUES
    #
    # STRATÉGIE DE CACHE PAR PROMPT :
    #
    # _SYSTEM_ICP   → appelé 1x par run → cache utile UNIQUEMENT en multi-run
    #                 (si l'agent est relancé dans les 5 min suivantes).
    #                 ~400 tokens : en dessous du seuil de 1024. On ne met
    #                 pas cache_control ici, ça ne servirait à rien.
    #
    # _SYSTEM_DORKS → même situation que _SYSTEM_ICP. Pas de cache_control.
    #
    # _SYSTEM_VALIDATION → appelé N fois par run (1 fois par URL candidate).
    #                 C'EST LE SEUL ENDROIT OÙ LE CACHE A UN IMPACT RÉEL.
    #                 Il doit :
    #                   1. Dépasser 1024 tokens (seuil Haiku) → few-shots ajoutés
    #                   2. Être byte-pour-byte identique sur tous les appels
    #                      → ICP + offer_type inclus ici (constants par run)
    #                      → construit UNE SEULE FOIS dans run() et passé à
    #                         chaque appel de validation
    # =========================================================================

    _SYSTEM_ICP = """
<role>
Tu es un stratège commercial B2B senior avec 15 ans d'expérience en définition
de profils clients idéaux (ICP — Ideal Customer Profile).
Tu transformes une intention commerciale floue en un ICP structuré, précis et
directement exploitable par un agent de prospection automatisé.
</role>

<your_job>
À partir d'une phrase libre décrivant une offre et/ou un prospect visé,
tu extrais et enrichis toutes les dimensions nécessaires :
- Qui est le prospect (secteur, taille, géographie, décideur)
- Ce qu'on lui vend (type et description de l'offre)
- Quels signaux d'achat chercher sur son site web
- Quels problèmes ton offre résout pour lui
- Quels domaines parasites exclure lors de la recherche
</your_job>

<output_rules>
Retourne UNIQUEMENT un objet JSON valide respectant exactement ce schéma.
Aucun texte avant ou après. Tous les champs sont obligatoires.

{
  "sector": "Secteur principal",
  "sub_sectors": ["sous-secteur 1", "sous-secteur 2"],
  "company_size": "X à Y employés",
  "geography": "Ville/Région/Pays ciblé",
  "decision_maker_title": ["Titre décideur 1", "Titre décideur 2"],
  "offer_type": "Produit | Service",
  "offer_description": "Description courte de l'offre",
  "buying_signals": ["Signal 1", "Signal 2", "Signal 3"],
  "pain_points": ["Douleur 1", "Douleur 2", "Douleur 3"],
  "icp_description": "Paragraphe synthétique de 3-5 phrases décrivant le prospect idéal et ses besoins",
  "excluded_domains_extra": ["annuaire-sectoriel.ca", "forum-metier.com"]
}
</output_rules>
"""

    _SYSTEM_DORKS = """
<role>
Tu es un expert en OSINT et en génération de Google Dorks pour la prospection B2B.
Tu génères des requêtes précises, exploitables directement dans Google Search.
</role>

<strategy>
Génère 2 dorks par sous-secteur fourni pour maximiser la diversité des prospects.
Chaque dork doit :
- Cibler explicitement le sous-secteur concerné
- Privilégier des pages riches en contenu qualifiant :
  pages "À propos", "Équipe", "Contact", annonces de recrutement, communiqués de croissance
- Rester dans la géographie de l'ICP
- Éviter les annuaires, les job boards et les médias généralistes
</strategy>

<output_rules>
Retourne UNIQUEMENT un tableau JSON de chaînes. Maximum 10 éléments. Aucun texte avant ou après.
Exemple : ["intitle:\\"À propos\\" \\"BTP\\" \\"Québec\\"", "intext:\\"recrutement\\" \\"construction\\" site:.ca"]
</output_rules>
"""

    # [C1][C2] Template du system message de validation.
    # Les placeholders {offer_type} et {icp_criteria} sont injectés UNE SEULE
    # FOIS dans run() via _build_validation_system_msg().
    # Les few-shots exemples (~600 tokens) + instructions (~400 tokens)
    # + ICP injecté (~300 tokens) → total > 1024 tokens → cache activé.
    _SYSTEM_VALIDATION_TEMPLATE = """
<role>
Tu es un analyste commercial senior spécialisé en qualification B2B.
Tu analyses le contenu textuel d'un site web et décides s'il correspond
au profil ICP et à l'offre ci-dessous. Ta décision impacte directement
le chiffre d'affaires : un faux positif gaspille le temps des commerciaux,
un faux négatif fait rater une opportunité réelle.
</role>

<offer_context>
Offre commercialisée : {offer_type}
</offer_context>

<icp_criteria>
{icp_criteria}
</icp_criteria>

<analysis_steps>
1. Identifie le nom de l'entreprise et son secteur d'activité principal.
2. Vérifie la localisation géographique par rapport à l'ICP.
3. Estime la taille de l'entreprise si des indices sont présents
   (nombre d'employés, nombre de projets, chiffre d'affaires mentionné).
4. Cherche des signaux d'achat explicites : offres d'emploi, annonces de
   croissance, nouveaux contrats, changement de direction, mention d'un
   problème que l'offre résout.
5. Évalue si l'entreprise a un BESOIN POTENTIEL pour l'offre décrite.
6. Décide : VALIDE (correspond à l'ICP ET a un besoin probable) ou INVALIDE.
</analysis_steps>

<few_shot_examples>
EXEMPLE 1 — Prospect VALIDE
Offre : Service de gestion de paie externalisée
ICP : PME manufacturières, 50-200 employés, Ontario, Canada
Contenu site analysé : "Fondée en 1998, Métaux Brampton Inc. est spécialisée
dans la fabrication de pièces d'aluminium pour l'industrie automobile.
Nos 85 employés opèrent sur 3 lignes de production. Nous recrutons
actuellement un contrôleur financier pour accompagner notre croissance."
Résultat attendu :
{{"valid": true, "company_name": "Métaux Brampton Inc.", "industry": "Fabrication / Aluminium",
 "signals": ["85 employés confirmés", "recrutement contrôleur financier = signal de croissance financière"],
 "fit_reason": "PME manufacturière ontarienne de 85 employés en croissance, cherche du renfort financier — besoin probable d'externalisation de paie."}}

EXEMPLE 2 — Prospect INVALIDE (hors géographie)
Offre : Service de gestion de paie externalisée
ICP : PME manufacturières, 50-200 employés, Ontario, Canada
Contenu site analysé : "TechnoPlast SAS est une PME industrielle basée à Lyon,
France, spécialisée dans l'injection plastique depuis 2005. 120 collaborateurs."
Résultat attendu :
{{"valid": false, "reason": "Entreprise française (Lyon), hors zone géographique ICP (Ontario, Canada)."}}

EXEMPLE 3 — Prospect INVALIDE (mauvais secteur)
Offre : Logiciel de gestion de chantier BTP
ICP : Entreprises de construction, Québec, 10-100 employés
Contenu site analysé : "Cabinet Beaumont & Associés, experts-comptables à
Montréal depuis 1987. Notre équipe de 25 professionnels vous accompagne
dans vos obligations fiscales et comptables."
Résultat attendu :
{{"valid": false, "reason": "Cabinet comptable, pas une entreprise de construction."}}

EXEMPLE 4 — Prospect VALIDE avec signal fort
Offre : Logiciel de gestion de chantier BTP
ICP : Entreprises de construction, Québec, 10-100 employés
Contenu site analysé : "Construction Dallaire, entrepreneur général à Québec.
Depuis 2010, nous réalisons des projets résidentiels et commerciaux partout
en Chaudière-Appalaches. Équipe de 40 charpentiers et gestionnaires de projet.
Nous cherchons à améliorer le suivi de nos chantiers. Poste ouvert :
coordonnateur de chantier."
Résultat attendu :
{{"valid": true, "company_name": "Construction Dallaire", "industry": "Construction / Entrepreneur général",
 "signals": ["40 employés", "recrutement coordonnateur chantier", "mention explicite d'un besoin de suivi de chantier"],
 "fit_reason": "Entrepreneur général québécois de 40 employés cherchant explicitement à améliorer le suivi de chantier — besoin direct pour un logiciel de gestion BTP."}}
</few_shot_examples>

<output_rules>
Retourne UNIQUEMENT un objet JSON valide. Aucun texte avant ou après.
Si VALIDE :
  {{"valid": true, "company_name": "...", "industry": "...", "signals": ["..."], "fit_reason": "Explication du besoin pour l'offre spécifique"}}
Si INVALIDE :
  {{"valid": false, "reason": "Raison concise (géographie, secteur, taille, ou autre)"}}
</output_rules>
"""

    def __init__(self, output_file: str = "prospects_output.jsonl"):
        self.zyte_client = AsyncZyteAPI(api_key=ZYTE_API_KEY)
        self.llm = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            temperature=0.2,
            api_key=ANTHROPIC_API_KEY,
            max_tokens=1024,
        )
        self.tracker = TokenTracker()

        self.output_path = Path(output_file)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        # [C5] Lock instancié UNE SEULE FOIS — partagé par tous les appels
        # concurrents à _persist_prospect. Instancier Lock() dans la méthode
        # crée un verrou indépendant à chaque appel → protection illusoire.
        self._file_lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # [C3][C4] Construction du system message de validation (une fois par run)
    # -------------------------------------------------------------------------

    def _build_validation_system_msg(
        self, icp_criteria: str, offer_type: str
    ) -> SystemMessage:
        """
        Construit le SystemMessage de validation en injectant l'ICP et
        l'offer_type dans le template statique.

        Pourquoi construire ici plutôt que dans _validate_raw ?
        → Le message doit être byte-pour-byte IDENTIQUE sur tous les appels
          de validation du run pour que le cache Anthropic soit hit.
          Si on le construisait dans _validate_raw, une différence de whitespace
          ou d'encodage pourrait invalider le cache silencieusement.

        Taille estimée du bloc mis en cache :
          - Instructions + few-shots : ~900 tokens
          - ICP injecté              : ~200-400 tokens (variable)
          - offer_type               : ~20-50 tokens
          Total                      : ~1120-1350 tokens → au-dessus du seuil
          de 1024 tokens requis par Claude Haiku pour activer le cache.
        """
        filled_prompt = self._SYSTEM_VALIDATION_TEMPLATE.format(
            offer_type=offer_type,
            icp_criteria=icp_criteria,
        )
        return SystemMessage(content=[{
            "type": "text",
            "text": filled_prompt,
            # cache_control active le cache Anthropic sur ce bloc.
            # Coût : écriture facturée à 1.25x lors du 1er appel.
            # Bénéfice : tous les appels suivants lisent au cache à 0.1x.
            # Break-even : dès le 2ème appel de validation dans le run.
            "cache_control": {"type": "ephemeral"},
        }])

    # -------------------------------------------------------------------------
    # Persistance temps réel [C5]
    # -------------------------------------------------------------------------

    async def _persist_prospect(self, prospect: dict):
        """Écrit immédiatement un prospect validé dans le fichier JSONL."""
        prospect["saved_at"] = datetime.utcnow().isoformat()
        async with self._file_lock:   # [C5] self._file_lock, pas asyncio.Lock()
            with self.output_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(prospect, ensure_ascii=False) + "\n")
        logger.info(f"[persist] Prospect sauvegardé : {prospect.get('company_name')}")

    # -------------------------------------------------------------------------
    # Helper tracking tokens
    # -------------------------------------------------------------------------

    def _track(self, response):
        meta = getattr(response, "usage_metadata", None) or {}
        self.tracker.record(meta)

    # -------------------------------------------------------------------------
    # Fetch adaptatif [3]
    # -------------------------------------------------------------------------

    async def _fetch_url(self, url: str) -> Optional[str]:
        """
        Tente d'abord un fetch HTTP simple (rapide + pas cher).
        Si le body est vide ou trop court, repasse en browserHtml.
        """
        try:
            response = await self.zyte_client.get({
                "url": url,
                "httpResponseBody": True,
                "geolocation": "CA",
            })
            body_b64 = response.get("httpResponseBody", "")
            if body_b64:
                html = base64.b64decode(body_b64).decode("utf-8", errors="replace")
                if len(html.strip()) > 500:
                    logger.debug(f"[fetch] HTTP simple OK : {url}")
                    return html

            logger.debug(f"[fetch] Body insuffisant, passage en browserHtml : {url}")
            response2 = await self.zyte_client.get({
                "url": url,
                "browserHtml": True,
                "geolocation": "CA",
            })
            return response2.get("browserHtml")
        except Exception as e:
            logger.error(f"[fetch] Erreur Zyte pour {url} : {e}")
            return None

    # =========================================================================
    # ÉTAPE 0 : Génération de l'ICP
    # [C6] Cache cross-run uniquement (appelé 1x par run)
    # =========================================================================

    async def _generate_icp_raw(self, raw_phrase: str) -> ICPProfile:
        # Pas de cache_control : _SYSTEM_ICP < 1024 tokens, le cache
        # ne s'activerait pas sur Haiku. Annotating cache_control on a block
        # below the minimum generates a silent no-op and wastes a round-trip.
        system_msg = SystemMessage(content=self._SYSTEM_ICP)

        user_msg = HumanMessage(content=(
            f"Voici ma phrase de départ :\n\n\"{raw_phrase}\"\n\n"
            "Génère l'ICP complet correspondant."
        ))

        response = await self.llm.ainvoke([system_msg, user_msg])
        self._track(response)

        raw_data = parse_llm_json(response.content)
        if raw_data is None:
            raise ValueError("Le LLM n'a pas retourné de JSON valide pour l'ICP.")

        try:
            icp = ICPProfile(**raw_data)
            logger.info(
                f"[icp] Généré — Secteur: {icp.sector} | "
                f"Géo: {icp.geography} | Offre: {icp.offer_description}"
            )
            return icp
        except ValidationError as e:
            raise ValueError(f"Schéma ICP invalide : {e}")

    async def generate_icp(self, raw_phrase: str) -> ICPProfile:
        result = await retry_async(self._generate_icp_raw, raw_phrase)
        if result is None:
            raise RuntimeError("Impossible de générer l'ICP après plusieurs tentatives.")
        return result

    def _icp_to_pipeline_args(self, icp: ICPProfile) -> tuple[str, str]:
        enriched = (
            f"{icp.icp_description}\n\n"
            f"Signaux d'achat à détecter : {', '.join(icp.buying_signals)}.\n"
            f"Problèmes résolus par l'offre : {', '.join(icp.pain_points)}.\n"
            f"Décideurs ciblés : {', '.join(icp.decision_maker_title)}.\n"
            f"Taille d'entreprise : {icp.company_size}."
        )
        return enriched, f"{icp.offer_type} ({icp.offer_description})"

    # =========================================================================
    # ÉTAPE 1 : Génération des Google Dorks
    # [C6] Cache cross-run uniquement (appelé 1x par run)
    # =========================================================================

    async def _generate_queries_raw(
        self, icp_description: str, offer_type: str, sub_sectors: list[str]
    ) -> list[str]:
        # Pas de cache_control : _SYSTEM_DORKS < 1024 tokens.
        system_msg = SystemMessage(content=self._SYSTEM_DORKS)

        sub_sectors_str = "\n".join(f"- {s}" for s in sub_sectors)
        user_msg = HumanMessage(content=(
            f"<offer_type>{offer_type}</offer_type>\n\n"
            f"<icp_description>{icp_description}</icp_description>\n\n"
            f"<sub_sectors>\n{sub_sectors_str}\n</sub_sectors>\n\n"
            "Génère 2 Google Dorks par sous-secteur (maximum 10 au total). "
            "Chaque dork doit cibler un sous-secteur différent et prioriser "
            "les pages '/a-propos', '/equipe', les annonces de recrutement "
            "et les signaux de croissance."
        ))

        response = await self.llm.ainvoke([system_msg, user_msg])
        self._track(response)

        parsed = parse_llm_json(response.content)
        if not isinstance(parsed, list):
            logger.error("Le LLM n'a pas retourné une liste pour les dorks.")
            return []

        logger.info(f"[dorks] {len(parsed)} requêtes générées pour {len(sub_sectors)} sous-secteurs")
        return parsed

    async def generate_search_queries(
        self, icp: str, offer_type: str, sub_sectors: list[str]
    ) -> list[str]:
        result = await retry_async(self._generate_queries_raw, icp, offer_type, sub_sectors)
        return result or []

    # =========================================================================
    # ÉTAPE 2 : Recherche SERP
    # =========================================================================

    async def _search_google_raw(self, query: str) -> list[str]:
        logger.info(f"[serp] Requête : {query}")
        response = await self.zyte_client.get({
            "url": f"https://www.google.com/search?q={quote_plus(query)}&gl=ca&hl=fr",
            "serp": True,
            "geolocation": "CA",
        })
        organic = response.get("serp", {}).get("organicResults", [])
        urls = [r["url"] for r in organic if r.get("url")]
        logger.info(f"[serp] {len(urls)} URLs extraites.")
        return urls

    async def search_google(self, query: str) -> list[str]:
        result = await retry_async(self._search_google_raw, query)
        return result or []

    # =========================================================================
    # ÉTAPE 3 : Validation
    # [C1-C4] Le system_message est reçu pré-construit depuis run()
    # → identique byte-pour-byte sur tous les appels → cache hit garanti
    # =========================================================================

    async def _validate_raw(
        self,
        url: str,
        system_msg: SystemMessage,   # [C4] pré-construit, pas rebuildi ici
    ) -> Optional[dict]:

        html = await self._fetch_url(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "head"]):
            tag.decompose()
        text_content = soup.get_text(separator=" ", strip=True)[:8000]

        # User message = UNIQUEMENT le contenu du site (vraiment dynamique)
        user_msg = HumanMessage(
            content=f"<website_content>\n{text_content}\n</website_content>"
        )

        response = await self.llm.ainvoke([system_msg, user_msg])
        self._track(response)

        # Log du statut cache pour debug
        meta = getattr(response, "usage_metadata", {}) or {}
        cache_hit = meta.get("cache_read_input_tokens", 0)
        logger.debug(
            f"[cache] {url} — "
            f"cache_read={cache_hit} tokens | "
            f"{'✓ HIT' if cache_hit > 0 else '✗ MISS (1er appel ou TTL expiré)'}"
        )

        raw_data = parse_llm_json(response.content)
        if raw_data is None:
            return None

        try:
            if raw_data.get("valid") is True:
                prospect = ProspectValid(**raw_data)
                return {"url": url, **prospect.model_dump()}
            else:
                invalid = ProspectInvalid(**raw_data)
                logger.info(f"[valid] Invalide ({url}) : {invalid.reason}")
                return None
        except ValidationError as e:
            logger.error(f"[valid] Schéma Pydantic invalide pour {url} : {e}")
            return None

    async def validate_prospect_website(
        self, url: str, system_msg: SystemMessage
    ) -> Optional[dict]:
        return await retry_async(self._validate_raw, url, system_msg)

    # =========================================================================
    # ORCHESTRATEUR
    # =========================================================================

    async def run(
        self,
        icp_description: str,
        offer_type: str,
        sub_sectors: list[str] | None = None,
        max_urls: int = 100,
        max_concurrent_validations: int = 3,
        extra_excluded_domains: Optional[set[str]] = None,
    ) -> list[dict]:

        run_start = datetime.utcnow()
        effective_excluded = EXCLUDED_DOMAINS | (extra_excluded_domains or set())

        # 1. Dorks — 2 par sous-secteur si disponibles, sinon fallback générique
        queries = await self.generate_search_queries(
            icp_description, offer_type, sub_sectors or []
        )
        if not queries:
            logger.error("Aucune requête générée. Arrêt.")
            return []

        # 2. SERP parallèle
        serp_results = await asyncio.gather(
            *[self.search_google(q) for q in queries]
        )
        all_urls: list[str] = []
        for url_list in serp_results:
            all_urls.extend(url_list)

        candidate_urls = filter_and_deduplicate_urls(
            all_urls, max_urls, effective_excluded
        )
        logger.info(f"{len(candidate_urls)} URLs candidates (après filtre/dédup).")

        # [C3][C4] Construit UNE SEULE FOIS pour tout le run.
        # Toutes les validations reçoivent exactement le même objet
        # → le bloc est mis en cache au 1er appel, lu depuis le cache
        # sur tous les appels suivants (économie ~90% des tokens input).
        validation_system_msg = self._build_validation_system_msg(
            icp_criteria=icp_description,
            offer_type=offer_type,
        )

        # 3. Validation concurrente
        semaphore = asyncio.Semaphore(max_concurrent_validations)

        async def bounded_validate(url: str):
            async with semaphore:
                result = await self.validate_prospect_website(url, validation_system_msg)
                if result:
                    await self._persist_prospect(result)
                return result

        results = await asyncio.gather(
            *[bounded_validate(url) for url in candidate_urls]
        )
        prospects = [p for p in results if p is not None]

        # Rapport final
        cost = self.tracker.summary()
        duration = (datetime.utcnow() - run_start).total_seconds()
        cache_savings_pct = (
            round(cost["cache_read_tokens"] /
                  max(cost["input_tokens"] + cost["cache_read_tokens"], 1) * 100, 1)
        )
        logger.info(
            f"Run terminé en {duration:.1f}s | "
            f"{len(prospects)} prospects | "
            f"Coût : ${cost['estimated_cost_usd']:.5f} | "
            f"Cache read : {cost['cache_read_tokens']} tokens "
            f"({cache_savings_pct}% des tokens input lus depuis le cache)"
        )

        return prospects
