"""
Utilitaires partagés entre tous les modules.
"""

import asyncio
import json
import logging
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

EXCLUDED_DOMAINS = {
    "wikipedia.org", "linkedin.com", "facebook.com", "youtube.com",
    "instagram.com", "twitter.com", "x.com", "tiktok.com",
    "pages-jaunes.ca", "pagesjaunes.fr", "yelp.com", "yelp.ca",
    "google.com", "maps.google.com", "apple.com",
    "gouvernement.qc.ca", "canada.ca",
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


async def retry_async(coro_func, *args, max_retries=3, base_delay=2.0, **kwargs):
    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except Exception as e:
            wait = base_delay * (2 ** attempt)
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
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError as e:
        logger.error(f"Échec parsing JSON : {e} | Raw : {raw[:300]}")
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
) -> list[str]:
    """
    Filtre, déduplique par domaine racine et trie par score qualifiant.
    - Un seul URL par domaine racine (company.qc.ca = www.company.qc.ca)
    - URLs parasites (blog, emplois…) exclues avant validation Claude
    - Résultat trié par score décroissant : pages /a-propos en premier
    """
    seen_roots: set[str] = set()
    candidates: list[tuple[int, str]] = []  # (score, url)

    for url in ordered_urls:
        domain = urlparse(url).netloc
        if any(excl in domain for excl in excluded):
            logger.debug(f"[dedup] Domaine exclu : {url}")
            continue

        root = extract_root_domain(domain)
        if root in seen_roots:
            continue
        seen_roots.add(root)

        s = score_url(url)
        if s == -1:
            logger.debug(f"[dedup] Chemin parasite exclu : {url}")
            continue

        candidates.append((s, url))

    # Tri décroissant par score — pages /a-propos validées en premier
    candidates.sort(key=lambda x: x[0], reverse=True)
    result = [url for _, url in candidates[:max_urls]]
    logger.info(
        f"[dedup] {len(result)} URLs candidates "
        f"(scores: {[s for s, _ in candidates[:max_urls]]})"
    )
    return result
