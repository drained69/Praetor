from __future__ import annotations

from .core import Job, JobResult


class BasicVerifier:
    """Small deterministic safety gate used by the demo and tests."""

    def verify(self, job: Job, result: JobResult) -> tuple[bool, str]:
        if not result.output.strip():
            return False, "worker returned an empty report"
        if not result.success:
            return False, result.reason or "worker reported failure"
        return True, "report contains output and worker reported success"
