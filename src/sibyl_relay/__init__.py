"""Memory-backed agent coordination."""

from .env import load_env as _load_env

# Load a nearby .env so credentials are picked up automatically. Real
# environment variables that are already set take precedence.
_load_env()

from .core import Coordinator, Job, JobResult, WorkerProfile
from .memory import InMemoryStore, SibylMemoryStore
from .partners import BasePaymentAdapter, PartnerReceipt, VirtualsACPAdapter
from .verification import BasicVerifier

__all__ = [
    "Coordinator",
    "Job",
    "JobResult",
    "WorkerProfile",
    "InMemoryStore",
    "SibylMemoryStore",
    "BasicVerifier",
    "BasePaymentAdapter",
    "VirtualsACPAdapter",
    "PartnerReceipt",
]
