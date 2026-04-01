"""
Schémas Pydantic partagés entre tous les modules.
"""

from pydantic import BaseModel


# =============================================================================
# MODULE 1 — Prospect Finder
# =============================================================================

class ICPProfile(BaseModel):
    sector: str
    sub_sectors: list[str]
    company_size: str
    geography: str
    decision_maker_title: list[str]
    offer_type: str
    offer_description: str
    buying_signals: list[str]
    pain_points: list[str]
    icp_description: str
    excluded_domains_extra: list[str]


class ProspectValid(BaseModel):
    valid: bool
    company_name: str
    industry: str
    signals: list[str]
    fit_reason: str


class ProspectInvalid(BaseModel):
    valid: bool
    reason: str


# =============================================================================
# MODULE 2 — Contact Enricher (à implémenter)
# =============================================================================

# class Contact(BaseModel):
#     company_url: str
#     full_name: str
#     title: str
#     email: str
#     email_confidence: float          # 0.0 – 1.0
#     linkedin_url: str | None
#     source: str                      # "scrape" | "hunter" | "linkedin"
#     enriched_at: str                 # ISO timestamp


# =============================================================================
# MODULE 3 — Personalization Agent (à implémenter)
# =============================================================================

# class MessageRecord(BaseModel):
#     prospect_url: str
#     contact_email: str
#     subject: str
#     body: str
#     score: int                       # 0–100
#     variant_index: int               # 0, 1 ou 2
#     generated_at: str                # ISO timestamp


# =============================================================================
# MODULE 4 — Sequencer (à implémenter)
# =============================================================================

# class SequenceState(BaseModel):
#     prospect_url: str
#     contact_email: str
#     status: str                      # "pending" | "sent" | "replied" | "unsubscribed"
#     intent: str | None               # "interested" | "not_now" | "not_relevant" | "unsubscribe"
#     next_action_at: str | None       # ISO timestamp
#     crm_pushed: bool
