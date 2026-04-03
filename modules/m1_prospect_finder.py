"""
=============================================================================
MODULE 1 : RECHERCHE & QUALIFICATION DE PROSPECTS — v6
Agent Commercial Autonome — Brique Fondatrice
=============================================================================
Améliorations v6 — Migration Ollama Cloud :
  [O1] Remplacement de ChatAnthropic par ChatOllama (modèles open source)
  [O2] Authentification via OLLAMA_API_KEY (créer sur https://ollama.com/settings)
  [O3] URL par défaut : https://ollama.com (Ollama Cloud)
  [O4] Variable OLLAMA_MODEL pour choisir le modèle
  [O5] Suppression du prompt caching (non supporté par Ollama)
  [O6] Coût = $0 (modèles cloud avec quota gratuit)

Améliorations v5 — Généricité :
  [G1] Few-shots générés dynamiquement via generate_few_shots()
  [G2] Géographie configurable via extract_geo_code()
  [G3] main.py accepte --phrase en argument CLI
  [G4] Paramètre icp_summary optionnel

Améliorations v3-v4 :
  [1] offer_type transmis jusqu'à la validation
  [2] Filtre de domaines exclus avant validation
  [3] Fetch adaptatif : httpResponseBody d'abord, browserHtml si vide
  [4] Déduplication par domaine
  [5] Ordre SERP préservé
  [6] Persistance temps réel (crash-safe)
  [7] Génération des dorks via SystemMessage/HumanMessage
  [8] Tracking des tokens par run
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
from urllib.parse import quote_plus, urlparse

from zyte_api import AsyncZyteAPI
from bs4 import BeautifulSoup
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import ValidationError
from dotenv import load_dotenv

from core.schemas import ICPProfile, ProspectValid, ProspectInvalid
from core.token_tracker import TokenTracker
from core.utils import EXCLUDED_DOMAINS, retry_async, parse_llm_json, filter_and_deduplicate_urls, extract_root_domain, extract_geo_code

# =============================================================================
# CONFIGURATION
# =============================================================================

load_dotenv()

ZYTE_API_KEY = os.getenv("ZYTE_API_KEY")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

if not ZYTE_API_KEY:
    raise EnvironmentError(
        "Variable manquante dans .env : ZYTE_API_KEY"
    )
if not OLLAMA_API_KEY:
    raise EnvironmentError(
        "Variable manquante dans .env : OLLAMA_API_KEY\n"
        "Créez une clé sur https://ollama.com/settings"
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
IMPORTANT pour sub_sectors : génère UN sous-secteur distinct pour chaque type de profession
ou secteur cité dans la phrase. Si 10 professions sont mentionnées, tu dois avoir ~10 sous-secteurs.
Ne regroupe jamais des professions distinctes en un seul sous-secteur générique.

{
  "sector": "Secteur principal",
  "sub_sectors": ["sous-secteur 1", "sous-secteur 2", "...un sous-secteur distinct par type de profession ou secteur cité"],
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
- JAMAIS utiliser filetype:pdf — les PDFs sont illisibles et gaspillent des appels
- Toujours ajouter -filetype:pdf à chaque requête
</strategy>

<output_rules>
Retourne UNIQUEMENT un tableau JSON de chaînes. Maximum 20 éléments. Aucun texte avant ou après.
Exemple : ["intitle:\\"À propos\\" \\"BTP\\" \\"Québec\\"", "intext:\\"recrutement\\" \\"construction\\" site:.ca"]
</output_rules>
"""

    # [C1][C2] Template du system message de validation.
    # Les placeholders {offer_type} et {icp_criteria} sont injectés UNE SEULE
    # FOIS dans run() via _build_validation_system_msg().
    # Les few-shots exemples (~600 tokens) + instructions (~400 tokens)
    # + ICP injecté (~300 tokens) → total > 1024 tokens → cache activé.
    # Template de validation SANS few-shots hardcodés.
    # Les few-shots sont générés dynamiquement via generate_few_shots()
    # et injectés via le placeholder {few_shot_examples}.
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
{few_shot_examples}
</few_shot_examples>

<output_rules>
Retourne UNIQUEMENT un objet JSON valide. Aucun texte avant ou après.
Si VALIDE :
  {{"valid": true, "company_name": "...", "industry": "...", "signals": ["..."], "fit_reason": "Explication du besoin pour l'offre spécifique"}}
Si INVALIDE :
  {{"valid": false, "reason": "Raison concise, MAX 20 mots (ex: hors géo, secteur public, trop grand, annuaire, PDF illisible)"}}
</output_rules>
"""

    # Prompt pour générer les few-shots dynamiques
    _SYSTEM_FEW_SHOTS = """
<role>
Tu es un expert en création d'exemples d'entraînement pour la qualification B2B.
Tu génères des exemples réalistes qui illustrent comment qualifier des prospects
selon un ICP et une offre spécifiques.
</role>

<task>
Génère 3 exemples de qualification de prospects :
- 2 exemples VALIDE (avec des raisons de fit différentes)
- 1 exemple INVALIDE (raison typique : mauvaise taille, mauvaise géographie, hors cible)

Chaque exemple doit être cohérent avec l'ICP et l'offre fournis.
Les exemples doivent illustrer des cas variés mais réalistes.
</task>

<output_rules>
Retourne UNIQUEMENT un tableau JSON de 3 objets. Format de chaque objet :
{
  "description": "EXEMPLE N — Prospect VALIDE/INVALIDE (raison courte)",
  "offer": "Type d'offre",
  "icp_summary": "Résumé de l'ICP",
  "site_content": "Contenu fictif mais réaliste du site web analysé",
  "result": {"valid": true/false, ...}
}
Aucun texte avant ou après. JSON strictement valide.
</output_rules>
"""

    def __init__(self, output_file: str = "prospects_output.jsonl"):
        self.zyte_client = AsyncZyteAPI(api_key=ZYTE_API_KEY)

        # Client Ollama via langchain-ollama
        ollama_headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}"}

        self.llm = ChatOllama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=0.2,
            num_predict=8192,
            client_kwargs={"headers": ollama_headers},
        )

        self.llm_validate = ChatOllama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=0.1,
            num_predict=1024,
            client_kwargs={"headers": ollama_headers},
        )

        self.tracker = TokenTracker()

        self.output_path = Path(output_file)
        self.rejected_path = self.output_path.parent / "rejected.jsonl"
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # Helper
    # -------------------------------------------------------------------------

    def _track(self, response):
        meta = getattr(response, "usage_metadata", None) or {}
        self.tracker.record(meta)

    # -------------------------------------------------------------------------
    # Construction du system message de validation
    # -------------------------------------------------------------------------

    async def generate_few_shots(
        self, icp_description: str, offer_type: str, icp_summary: str
    ) -> str:
        """
        Génère 3 exemples de qualification dynamiquement basés sur l'ICP.
        Ces exemples sont injectés dans le prompt de validation pour
        adapter le few-shot learning au contexte spécifique de l'offre.
        """
        system_msg = SystemMessage(content=self._SYSTEM_FEW_SHOTS)
        user_msg = HumanMessage(content=(
            f"<offer_type>{offer_type}</offer_type>\n\n"
            f"<icp_description>{icp_description}</icp_description>\n\n"
            f"<icp_summary>{icp_summary}</icp_summary>\n\n"
            "Génère 3 exemples de qualification réalistes pour ce contexte."
        ))

        response = await self.llm.ainvoke([system_msg, user_msg])
        self._track(response)

        parsed = parse_llm_json(response.content)
        if not isinstance(parsed, list) or len(parsed) < 3:
            logger.warning("[few_shots] Échec génération, utilisation exemples génériques")
            return self._fallback_few_shots()

        # Formate les exemples en texte pour injection dans le prompt
        examples_text = []
        for i, ex in enumerate(parsed[:3], 1):
            examples_text.append(
                f"EXEMPLE {i} — {ex.get('description', f'Prospect {i}')}\n"
                f"Offre : {ex.get('offer', offer_type)}\n"
                f"ICP : {ex.get('icp_summary', icp_summary)}\n"
                f"Contenu site analysé : \"{ex.get('site_content', 'Contenu non spécifié')}\"\n"
                f"Résultat attendu :\n{json.dumps(ex.get('result', {}), ensure_ascii=False)}"
            )

        logger.info(f"[few_shots] {len(examples_text)} exemples générés")
        return "\n\n".join(examples_text)

    def _fallback_few_shots(self) -> str:
        """Exemples génériques de fallback si la génération dynamique échoue."""
        return """EXEMPLE 1 — Prospect VALIDE (correspondance ICP)
Offre : Offre commerciale
ICP : Profil cible défini
Contenu site analysé : "Entreprise correspondant au profil ICP avec signaux d'achat visibles."
Résultat attendu :
{"valid": true, "company_name": "Exemple Entreprise", "industry": "Secteur", "signals": ["Signal 1", "Signal 2"], "fit_reason": "Correspond au profil ICP et présente des signaux de besoin."}

EXEMPLE 2 — Prospect VALIDE (avec signaux forts)
Offre : Offre commerciale
ICP : Profil cible défini
Contenu site analysé : "Entreprise en croissance avec besoins identifiés correspondant à l'offre."
Résultat attendu :
{"valid": true, "company_name": "Exemple Croissance", "industry": "Secteur", "signals": ["Signal croissance", "Besoin identifié"], "fit_reason": "En croissance et besoin explicite de l'offre."}

EXEMPLE 3 — Prospect INVALIDE (hors cible)
Offre : Offre commerciale
ICP : Profil cible défini
Contenu site analysé : "Entreprise ne correspondant pas aux critères ICP."
Résultat attendu :
{"valid": false, "reason": "Hors cible ICP."}"""

    def _build_validation_system_msg(
        self, icp_criteria: str, offer_type: str, few_shot_examples: str = ""
    ) -> SystemMessage:
        """
        Construit le SystemMessage de validation.
        """
        filled_prompt = self._SYSTEM_VALIDATION_TEMPLATE.format(
            offer_type=offer_type,
            icp_criteria=icp_criteria,
            few_shot_examples=few_shot_examples or self._fallback_few_shots(),
        )
        return SystemMessage(content=filled_prompt)

    # -------------------------------------------------------------------------
    # Persistance temps réel [C5]
    # -------------------------------------------------------------------------

    async def _persist_prospect(self, prospect: dict):
        """Écrit immédiatement un prospect validé dans le fichier JSONL."""
        prospect["saved_at"] = datetime.utcnow().isoformat()
        async with self._file_lock:
            with self.output_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(prospect, ensure_ascii=False) + "\n")
        logger.info(f"[persist] Prospect sauvegardé : {prospect.get('company_name')}")

    async def _persist_rejected(self, url: str, reason: str):
        """Écrit immédiatement un prospect rejeté dans rejected.jsonl."""
        record = {"url": url, "reason": reason, "rejected_at": datetime.utcnow().isoformat()}
        async with self._file_lock:
            with self.rejected_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # -------------------------------------------------------------------------
    # Chargement des domaines déjà prospectés
    # -------------------------------------------------------------------------

    def _load_seen_domains(self) -> set[str]:
        """
        Charge les domaines racines depuis prospects.jsonl ET rejected.jsonl.
        Aucun domaine déjà visité (valide ou invalide) ne sera re-analysé.
        """
        seen = set()
        for path in (self.output_path, self.rejected_path):
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        url = record.get("url", "")
                        if url:
                            seen.add(extract_root_domain(urlparse(url).netloc))
                    except json.JSONDecodeError:
                        continue
        if seen:
            logger.info(f"[seen] {len(seen)} domaines déjà visités chargés (valides + rejetés)")
        return seen

    # -------------------------------------------------------------------------
    # Fetch adaptatif
    # -------------------------------------------------------------------------

    async def _fetch_url(self, url: str, geo_code: str = "CA") -> Optional[str]:
        """
        Tente d'abord un fetch HTTP simple (rapide + pas cher).
        Si le body est vide ou trop court, repasse en browserHtml.
        """
        try:
            response = await self.zyte_client.get({
                "url": url,
                "httpResponseBody": True,
                "geolocation": geo_code,
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
                "geolocation": geo_code,
            })
            return response2.get("browserHtml")
        except Exception as e:
            logger.error(f"[fetch] Erreur Zyte pour {url} : {e}")
            return None

    # =========================================================================
    # ÉTAPE 0 : Génération de l'ICP
    # =========================================================================

    async def _generate_icp_raw(self, raw_phrase: str) -> ICPProfile:
        system_msg = SystemMessage(content=self._SYSTEM_ICP)
        user_msg = HumanMessage(content=(
            f"Voici ma phrase de départ :\n\n\"{raw_phrase}\"\n\n"
            "Génère l'ICP complet correspondant."
        ))

        response = await self.llm.ainvoke([system_msg, user_msg])
        self._track(response)

        logger.info(f"[llm] Response ({len(response.content)} chars): {response.content[:300]}...")

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
    # =========================================================================

    async def _generate_queries_raw(
        self, icp_description: str, offer_type: str, sub_sectors: list[str]
    ) -> list[str]:
        sub_sectors_str = "\n".join(f"- {s}" for s in sub_sectors)

        system_msg = SystemMessage(content=self._SYSTEM_DORKS)
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
    # ÉTAPE 2 : Recherche SERP (avec pagination)
    # =========================================================================

    async def _search_google_page(self, query: str, start: int, geo_code: str = "CA") -> list[str]:
        """Fetche une page de résultats SERP (start=0 → p1, start=10 → p2…)."""
        # Map le code pays vers le paramètre gl de Google (lowercase)
        gl_param = geo_code.lower()
        response = await self.zyte_client.get({
            "url": f"https://www.google.com/search?q={quote_plus(query)}&gl={gl_param}&hl=fr&start={start}",
            "serp": True,
            "geolocation": geo_code,
        })
        organic = response.get("serp", {}).get("organicResults", [])
        return [r["url"] for r in organic if r.get("url")]

    async def _search_google_raw(self, query: str, serp_pages: int = 3, geo_code: str = "CA") -> list[str]:
        logger.info(f"[serp] Requête ({serp_pages}p) : {query}")
        pages = await asyncio.gather(*[
            self._search_google_page(query, start=i * 10, geo_code=geo_code)
            for i in range(serp_pages)
        ])
        urls = [url for page in pages for url in page]
        logger.info(f"[serp] {len(urls)} URLs extraites ({serp_pages} pages).")
        return urls

    async def search_google(self, query: str, serp_pages: int = 3, geo_code: str = "CA") -> list[str]:
        result = await retry_async(self._search_google_raw, query, serp_pages, geo_code)
        return result or []

    # =========================================================================
    # ÉTAPE 3 : Validation
    # =========================================================================

    async def _validate_raw(
        self,
        url: str,
        system_msg: SystemMessage,
        geo_code: str = "CA",
    ) -> Optional[dict]:

        # PDFs illisibles → rejet immédiat, sans appel Zyte ni LLM
        if url.lower().split("?")[0].endswith(".pdf"):
            logger.debug(f"[valid] PDF ignoré (non-analysable) : {url}")
            await self._persist_rejected(url, "Fichier PDF non-analysable.")
            return None

        html = await self._fetch_url(url, geo_code=geo_code)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "head"]):
            tag.decompose()
        text_content = soup.get_text(separator=" ", strip=True)[:3500]

        user_msg = HumanMessage(content=f"<website_content>\n{text_content}\n</website_content>")

        response = await self.llm_validate.ainvoke([system_msg, user_msg])
        self._track(response)

        logger.info(f"[llm] Response ({len(response.content)} chars)")

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
                await self._persist_rejected(url, invalid.reason)
                return None
        except ValidationError as e:
            logger.error(f"[valid] Schéma Pydantic invalide pour {url} : {e}")
            return None

    async def validate_prospect_website(
        self, url: str, system_msg: SystemMessage, geo_code: str = "CA"
    ) -> Optional[dict]:
        return await retry_async(self._validate_raw, url, system_msg, geo_code)

    # =========================================================================
    # ORCHESTRATEUR
    # =========================================================================

    async def run(
        self,
        icp_description: str,
        offer_type: str,
        sub_sectors: list[str] | None = None,
        max_urls: int = 1000,
        serp_pages: int = 3,
        max_concurrent_validations: int = 3,
        extra_excluded_domains: Optional[set[str]] = None,
        icp_summary: str = "",  # Résumé court de l'ICP pour few-shots
        geography: str = "",  # Géographie pour déterminer le code pays
    ) -> list[dict]:

        run_start = datetime.utcnow()
        effective_excluded = EXCLUDED_DOMAINS | (extra_excluded_domains or set())
        seen_domains = self._load_seen_domains()

        # Extraction du code pays depuis la géographie
        geo_code = extract_geo_code(geography) if geography else "CA"
        logger.info(f"[geo] Code pays : {geo_code} (depuis '{geography}')")

        # 1. Dorks — 2 par sous-secteur si disponibles, sinon fallback générique
        queries = await self.generate_search_queries(
            icp_description, offer_type, sub_sectors or []
        )
        if not queries:
            logger.error("Aucune requête générée. Arrêt.")
            return []

        # 2. SERP parallèle avec pagination
        serp_results = await asyncio.gather(
            *[self.search_google(q, serp_pages, geo_code=geo_code) for q in queries]
        )
        all_urls: list[str] = []
        for url_list in serp_results:
            all_urls.extend(url_list)

        candidate_urls = filter_and_deduplicate_urls(
            all_urls, max_urls, effective_excluded,
            already_seen=seen_domains if seen_domains else None,
        )

        logger.info(f"{len(candidate_urls)} URLs candidates (après filtre/dédup).")

        # 2.5. Génération des few-shots dynamiques
        few_shot_examples = await self.generate_few_shots(
            icp_description=icp_description,
            offer_type=offer_type,
            icp_summary=icp_summary or icp_description[:200],
        )

        # Construit le system prompt de validation une seule fois
        validation_system_msg = self._build_validation_system_msg(
            icp_criteria=icp_description,
            offer_type=offer_type,
            few_shot_examples=few_shot_examples,
        )

        # 3. Validation avec parallélisme
        semaphore = asyncio.Semaphore(3)
        _INTER_CALL_DELAY = 1.0

        async def bounded_validate(url: str):
            async with semaphore:
                result = await self.validate_prospect_website(url, validation_system_msg, geo_code=geo_code)
                if result:
                    await self._persist_prospect(result)
                await asyncio.sleep(_INTER_CALL_DELAY)
                return result

        results = await asyncio.gather(
            *[bounded_validate(url) for url in candidate_urls]
        )
        prospects = [p for p in results if p is not None]

        # Rapport final
        cost = self.tracker.summary()
        duration = (datetime.utcnow() - run_start).total_seconds()
        logger.info(
            f"Run terminé en {duration:.1f}s | "
            f"{len(prospects)} prospects | "
            f"Tokens : {cost['input_tokens']} in / {cost['output_tokens']} out"
        )

        return prospects
