"""
=============================================================================
POINT D'ENTRÉE — Agent Commercial Autonome
=============================================================================
Orchestrateur principal du pipeline :
  M1 → Prospect Finder    (opérationnel)
  M2 → Contact Enricher   (à venir)
  M3 → Personalization    (à venir)
  M4 → Sequencer          (à venir)
=============================================================================
"""

import argparse
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from modules.m1_prospect_finder import ProspectFinder

# from modules.m2_contact_enricher import ContactEnricher   # TODO: M2
# from modules.m3_personalization_agent import PersonalizationAgent  # TODO: M3
# from modules.m4_sequencer import Sequencer                # TODO: M4


def parse_args():
    parser = argparse.ArgumentParser(
        description="Agent Commercial Autonome — Recherche et qualification de prospects"
    )
    parser.add_argument(
        "--phrase", "-p",
        type=str,
        default=None,
        help="Description de votre offre et du prospect cible (si non fourni, prompt interactif)"
    )
    parser.add_argument(
        "--target", "-t",
        type=int,
        default=20,
        help="Nombre de prospects à trouver (défaut: 20)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="runs/prospects.jsonl",
        help="Fichier de sortie JSONL (défaut: runs/prospects.jsonl)"
    )
    return parser.parse_args()


def _params_for_target(target: int) -> dict:
    """
    Calcule max_urls et serp_pages selon le nombre de prospects visés.
    Hypothèse : ~30% des URLs candidates deviennent des prospects valides.
    Donc candidats nécessaires = target / 0.30.
    serp_pages et max_urls sont ajustés pour couvrir ce volume.

    | Cible | Candidats nécessaires | serp_pages | max_urls | Coût estimé |
    |-------|-----------------------|------------|----------|-------------|
    |    20 |          ~67          |     1      |    80    |   ~$0.03    |
    |    50 |         ~167          |     2      |   200    |   ~$0.08    |
    |   100 |         ~334          |     3      |   400    |   ~$0.15    |
    |   200 |         ~667          |     5      |   800    |   ~$0.28    |
    """
    needed = int(target / 0.30)
    if needed <= 80:
        return {"serp_pages": 1, "max_urls": 80}
    elif needed <= 200:
        return {"serp_pages": 2, "max_urls": 200}
    elif needed <= 400:
        return {"serp_pages": 3, "max_urls": 400}
    else:
        return {"serp_pages": 5, "max_urls": 800}


async def main():
    args = parse_args()

    # Phrase commerciale : CLI ou prompt interactif
    raw_phrase = args.phrase
    if not raw_phrase:
        print("\n" + "=" * 60)
        print("AGENT COMMERCIAL AUTONOME — M1 Prospect Finder")
        print("=" * 60)
        print("\nDécrivez votre offre et votre prospect cible.")
        print("Exemple : 'Je vends un CRM aux PME françaises de 10-50 employés...'")
        print("-" * 60)
        raw_phrase = input("\nVotre description : ").strip()
        if not raw_phrase:
            print("Description vide. Arrêt.")
            return

    target = args.target
    params = _params_for_target(target)

    print("\n" + "=" * 60)
    print("CONFIGURATION DU RUN")
    print("=" * 60)
    print(f"  Cible            : {target} prospects")
    print(f"  Pages SERP       : {params['serp_pages']} par requête")
    print(f"  Max URLs         : {params['max_urls']} candidats")
    print(f"  Modèle LLM       : {os.getenv('OLLAMA_MODEL', 'llama3.2')} (Ollama Cloud)")
    print(f"  Sortie           : {args.output}")

    agent = ProspectFinder(output_file=args.output)

    print("\n" + "=" * 60)
    print("ÉTAPE 0 — GÉNÉRATION DE L'ICP")
    print("=" * 60)

    icp = await agent.generate_icp(raw_phrase)

    print(f"\n  Secteur          : {icp.sector}")
    print(f"  Sous-secteurs    : {', '.join(icp.sub_sectors)}")
    print(f"  Taille           : {icp.company_size}")
    print(f"  Géographie       : {icp.geography}")
    print(f"  Décideurs        : {', '.join(icp.decision_maker_title)}")
    print(f"  Offre            : [{icp.offer_type}] {icp.offer_description}")
    print(f"  Signaux achat    : {', '.join(icp.buying_signals)}")
    print(f"  Douleurs cibles  : {', '.join(icp.pain_points)}")
    print(f"\n  ICP synthétique  :\n  {icp.icp_description}")
    if icp.excluded_domains_extra:
        print(f"\n  Domaines exclus  : {', '.join(icp.excluded_domains_extra)}")

    icp_description, offer_type = agent._icp_to_pipeline_args(icp)
    extra_excluded = set(icp.excluded_domains_extra)

    print("\n" + "=" * 60)
    print("ÉTAPES 1-3 — RECHERCHE & QUALIFICATION")
    print("=" * 60)

    prospects = await agent.run(
        icp_description=icp_description,
        offer_type=offer_type,
        sub_sectors=icp.sub_sectors,
        max_urls=params["max_urls"],
        serp_pages=params["serp_pages"],
        max_concurrent_validations=1,  # séquentiel, respecte la limite 50k tokens/min
        extra_excluded_domains=extra_excluded,
        icp_summary=icp.icp_description,
        geography=icp.geography,
    )

    print("\n" + "=" * 60)
    print(f"PROSPECTS QUALIFIÉS — {len(prospects)} résultats")
    print("=" * 60)
    for p in prospects:
        print(f"\n  Entreprise  : {p.get('company_name')}")
        print(f"  Secteur     : {p.get('industry')}")
        print(f"  Fit offre   : {p.get('fit_reason')}")
        print(f"  Signaux     : {', '.join(p.get('signals', []))}")
        print(f"  URL         : {p.get('url')}")
        print("  " + "-" * 40)

    summary = agent.tracker.summary()
    print(f"\nTokens utilisés : {summary['input_tokens']} in / {summary['output_tokens']} out")
    print(f"Modèle Ollama   : {summary.get('model', 'N/A')}")
    print(f"Résultats       : {agent.output_path}")


if __name__ == "__main__":
    asyncio.run(main())
