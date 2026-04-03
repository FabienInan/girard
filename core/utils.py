"""
Utilitaires partagés entre tous les modules.
"""

import asyncio
import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Mapping géographie → code pays Zyte/Google
GEO_TO_CODE = {
    # Canada
    "canada": "CA",
    "québec": "CA",
    "quebec": "CA",
    "ontario": "CA",
    "colombie-britannique": "CA",
    "british columbia": "CA",
    "alberta": "CA",
    "manitoba": "CA",
    "saskatchewan": "CA",
    "nouveau-brunswick": "CA",
    "new brunswick": "CA",
    "nouvelle-écosse": "CA",
    "nova scotia": "CA",
    "terreneuve": "CA",
    "newfoundland": "CA",
    "montréal": "CA",
    "montreal": "CA",
    "toronto": "CA",
    "vancouver": "CA",
    "calgary": "CA",
    "ottawa": "CA",
    # France
    "france": "FR",
    "paris": "FR",
    "lyon": "FR",
    "marseille": "FR",
    "bordeaux": "FR",
    "lille": "FR",
    "toulouse": "FR",
    "nice": "FR",
    # États-Unis
    "usa": "US",
    "united states": "US",
    "états-unis": "US",
    "etats-unis": "US",
    "new york": "US",
    "california": "US",
    "californie": "US",
    "texas": "US",
    "florida": "US",
    "floride": "US",
    # Europe
    "belgique": "BE",
    "belgium": "BE",
    "suisse": "CH",
    "switzerland": "CH",
    "luxembourg": "LU",
    "allemagne": "DE",
    "germany": "DE",
    "royaume-uni": "GB",
    "united kingdom": "GB",
    "uk": "GB",
    "espagne": "ES",
    "spain": "ES",
    "italie": "IT",
    "italy": "IT",
    "pays-bas": "NL",
    "netherlands": "NL",
    # Autre
    "maroc": "MA",
    "morocco": "MA",
    "algérie": "DZ",
    "algeria": "DZ",
    "tunisie": "TN",
    "tunisia": "TN",
    "sénégal": "SN",
    "senegal": "SN",
    "côte d'ivoire": "CI",
    "ivoire": "CI",
}


def extract_geo_code(geography: str) -> str:
    """
    Extrait un code pays Zyte/Google depuis une chaîne de géographie.
    Retourne 'CA' par défaut si aucun match trouvé.

    Exemples :
      "PME françaises de 10-50 employés" → "FR"
      "Entrepreneurs au Québec" → "CA"
      "Companies in New York" → "US"
    """
    if not geography:
        return "CA"

    geo_lower = geography.lower()

    # Cherche d'abord une correspondance directe
    for key, code in GEO_TO_CODE.items():
        if key in geo_lower:
            return code

    # Patterns communs
    if re.search(r"\b(fr|français|france)\b", geo_lower):
        return "FR"
    if re.search(r"\b(ca|canada|québec|quebec)\b", geo_lower):
        return "CA"
    if re.search(r"\b(us|usa|united states|états-unis|etats-unis)\b", geo_lower):
        return "US"

    # Défaut
    logger.info(f"[geo] Code pays non trouvé pour '{geography}', défaut: CA")
    return "CA"


EXCLUDED_DOMAINS = {
    # Réseaux sociaux et annuaires
    "wikipedia.org", "linkedin.com", "facebook.com", "youtube.com",
    "instagram.com", "twitter.com", "x.com", "tiktok.com",
    "pages-jaunes.ca", "pagesjaunes.fr", "yelp.com", "yelp.ca",
    "google.com", "maps.google.com", "apple.com",
    # Gouvernements et institutions publiques
    "gouvernement.qc.ca", "canada.ca", "gc.ca", "gouv.qc.ca",
    "assnat.qc.ca", "ville.montreal.qc.ca",
    # Universités et cégeps (pas des PME)
    "uqam.ca", "umontreal.ca", "mcgill.ca", "concordia.ca",
    "ulaval.ca", "usherbrooke.ca", "uqtr.ca", "uqo.ca",
    "cegep", "cmontmorency.qc.ca", "cegep-rimouski.qc.ca",
    # Ordres professionnels (pas des entreprises clientes)
    "barreau.qc.ca", "cpaquebec.ca", "oiq.ca", "oaciq.com",
    "camq.ca", "odq.qc.ca",
    # Job boards
    "indeed.ca", "glassdoor.ca", "jobillico.com", "monster.ca",
    "emploiquebec.gouv.qc.ca",
}

# Seconds-level domains qui font partie du domaine racine (ex: company.qc.ca)
_KNOWN_SLDS = {"qc", "on", "bc", "ab", "mb", "sk", "ns", "nb", "pe", "nl",
               "co", "com", "org", "net", "gov", "edu"}

# Chemins d'URL à forte valeur qualifiante
_HIGH_VALUE_PATHS = {
    "a-propos", "about", "about-us", "qui-sommes-nous", "notre-entreprise",
    "notre-histoire", "histoire", "equipe", "team", "notre-equipe", "mission",
    "vision", "company", "entreprise",
}
# Chemins d'URL à valeur moyenne
_MEDIUM_VALUE_PATHS = {
    "contact", "nous-joindre", "contactez-nous", "coordonnees", "rejoindre",
}
# Chemins parasites à exclure avant validation Claude
_EXCLUDE_PATHS = {
    "blog", "actualites", "news", "emploi", "emplois", "carrieres", "carrières",
    "jobs", "job", "forum", "faq", "aide", "help", "boutique", "shop", "store",
    "panier", "cart", "checkout", "login", "compte", "account",
}


async def retry_async(coro_func, *args, max_retries=5, base_delay=2.0, **kwargs):
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except Exception as e:
            err_str = str(e)
            # Respecte le Retry-After si présent (ex: 429 rate limit Anthropic = 60s)
            retry_after = None
            if "Retry-After" in err_str:
                import re
                m = re.search(r"'Retry-After':\s*'(\d+)'", err_str)
                if m:
                    retry_after = int(m.group(1))
            wait = retry_after if retry_after else base_delay * (2 ** attempt)
            logger.warning(
                f"[retry] {coro_func.__name__} tentative {attempt + 1}/{max_retries} "
                f"— retry dans {wait:.0f}s ({e})"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(wait)
            else:
                logger.error(f"[retry] Abandon définitif de {coro_func.__name__}.")
                return None


def parse_llm_json(raw: str) -> Optional[dict | list]:
    """
    Parse JSON from LLM output with repair attempts for common issues.
    Handles: code blocks, trailing commas, missing commas, truncated JSON.
    """
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0]

    raw = raw.strip()

    # First attempt: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Second attempt: repair trailing commas
    # Remove commas before ] or }
    repaired = re.sub(r',\s*([}\]])', r'\1', raw)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Third attempt: fix missing commas between objects/items
    # Pattern: "} {" or "] {" or "} [" should be "}, {" or "], {" or "}, ["
    repaired = re.sub(r'([}\]])\s*([{\[])', r'\1, \2', raw)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Fourth attempt: find JSON object/array boundaries
    # Sometimes LLM adds text before/after
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start_idx = raw.find(start_char)
        end_idx = raw.rfind(end_char)
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            extracted = raw[start_idx:end_idx + 1]
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                # Try repairs on extracted
                repaired = re.sub(r',\s*([}\]])', r'\1', extracted)
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

    logger.error(f"Échec parsing JSON après réparations | Raw : {raw[:500]}")
    return None


def extract_root_domain(domain: str) -> str:
    """
    Extrait le domaine racine en supprimant les sous-domaines.
    Gère les SLDs canadiens : www.company.qc.ca → company.qc.ca
                              blog.company.ca   → company.ca
    """
    parts = domain.split(".")
    if len(parts) >= 3 and parts[-2] in _KNOWN_SLDS:
        return ".".join(parts[-3:])  # company.qc.ca
    if len(parts) >= 2:
        return ".".join(parts[-2:])  # company.ca
    return domain


def score_url(url: str) -> int:
    """
    Score un URL selon la qualité qualifiante de son chemin.
      2  → page riche en contenu sur l'entreprise (/a-propos, /equipe…)
      1  → page de contact
      0  → page neutre (accueil, services…)
     -1  → page parasite à exclure (blog, emplois, panier…)
    """
    path = urlparse(url).path.lower().strip("/")
    # Cherche dans les segments du chemin (pas juste le début)
    segments = set(path.replace("-", "-").split("/"))
    # Vérifie aussi les sous-chaînes pour "a-propos" dans "/fr/a-propos"
    for keyword in _EXCLUDE_PATHS:
        if any(keyword in seg for seg in segments):
            return -1
    for keyword in _HIGH_VALUE_PATHS:
        if any(keyword in seg for seg in segments):
            return 2
    for keyword in _MEDIUM_VALUE_PATHS:
        if any(keyword in seg for seg in segments):
            return 1
    return 0


def filter_and_deduplicate_urls(
    ordered_urls: list[str],
    max_urls: int,
    excluded: set[str] = EXCLUDED_DOMAINS,
    already_seen: set[str] | None = None,
) -> list[str]:
    """
    Filtre, déduplique par domaine racine et trie par score qualifiant.
    - Un seul URL par domaine racine (company.qc.ca = www.company.qc.ca)
    - URLs parasites (blog, emplois…) exclues avant validation Claude
    - Domaines déjà visités (already_seen) exclus avant application du cap
    - Résultat trié par score décroissant : pages /a-propos en premier
    - Le cap max_urls est appliqué sur les URLs nouvelles uniquement
    """
    seen_roots: set[str] = set()
    candidates: list[tuple[int, str]] = []  # (score, url)
    skipped_seen = 0

    for url in ordered_urls:
        domain = urlparse(url).netloc
        if any(excl in domain for excl in excluded):
            logger.debug(f"[dedup] Domaine exclu : {url}")
            continue

        root = extract_root_domain(domain)
        if root in seen_roots:
            continue
        seen_roots.add(root)

        if already_seen and root in already_seen:
            skipped_seen += 1
            logger.debug(f"[dedup] Déjà visité : {url}")
            continue

        s = score_url(url)
        if s == -1:
            logger.debug(f"[dedup] Chemin parasite exclu : {url}")
            continue

        candidates.append((s, url))

    # Tri décroissant par score — pages /a-propos validées en premier
    candidates.sort(key=lambda x: x[0], reverse=True)
    result = [url for _, url in candidates[:max_urls]]
    logger.info(
        f"[dedup] {len(result)} URLs nouvelles candidates "
        f"({skipped_seen} déjà visitées ignorées) "
        f"(scores: {[s for s, _ in candidates[:max_urls]]})"
    )
    return result
