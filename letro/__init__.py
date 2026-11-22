"""LETRO — Ledger Evidence & Traceable Reward Oracle.

A deterministic, offline RL environment for financial-audit agents.
"""

from .env import AuditEnv
from .factory import env_from_episode, make_env
from .lazy import LetroEnv

__version__ = "1.0.0"
__all__ = ["AuditEnv", "LetroEnv", "env_from_episode", "make_env", "__version__"]
