"""
Tracking des tokens par run.

Note: Avec Ollama (modèles locaux), le coût est de $0.
Le tracker sert uniquement à mesurer l'utilisation des tokens.
"""

import os


class TokenTracker:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2")

    def record(self, usage_metadata: dict):
        if not usage_metadata:
            return
        self.input_tokens += usage_metadata.get("input_tokens", 0)
        self.output_tokens += usage_metadata.get("output_tokens", 0)

    @property
    def estimated_cost_usd(self) -> float:
        # Ollama = modèles locaux gratuits
        return 0.0

    def summary(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model": self.model,
            "estimated_cost_usd": 0.0,
        }
