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

import asyncio

from modules.m1_prospect_finder import ProspectFinder

# from modules.m2_contact_enricher import ContactEnricher   # TODO: M2
# from modules.m3_personalization_agent import PersonalizationAgent  # TODO: M3
# from modules.m4_sequencer import Sequencer                # TODO: M4


async def main():
    agent = ProspectFinder(output_file="runs/prospects.jsonl")

    raw_phrase = (
        "Je vends un logiciel de devis et soumissions (génération depuis templates, "
        "suivi en temps réel, signature électronique) au Québec pour deux profils équivalents : "

        "PROFIL A — PME 2 à 50 employés en construction et rénovation "
        "(entrepreneurs généraux, électriciens, plombiers, menuisiers, peintres, paysagistes) "
        "qui envoient des soumissions de travaux sur Word/Excel ou papier. "

        "PROFIL B — Professionnels indépendants ou petits cabinets 1 à 10 personnes "
        "qui envoient des propositions d'honoraires, lettres de mandat ou contrats de service "
        "avant de débuter leur travail : notaires, avocats, fiscalistes, comptables CPA, "
        "psychologues, dentistes, évaluateurs agréés, arpenteurs, ingénieurs conseil. "
        "Ces professionnels ont exactement le même besoin : formaliser, envoyer et faire "
        "signer un document de prix avant de commencer — sans système dédié aujourd'hui. "

        "Les deux profils envoient 5 à 20 de ces documents par mois."
    )
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
        max_urls=20,
        max_concurrent_validations=3,
        extra_excluded_domains=extra_excluded,
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

    print(f"\nCoût total : ${agent.tracker.estimated_cost_usd:.5f} USD")
    print(f"Résultats  : {agent.output_path}")


if __name__ == "__main__":
    asyncio.run(main())
