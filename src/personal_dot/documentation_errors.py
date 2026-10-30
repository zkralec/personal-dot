"""Fixed documentation-preview diagnostics, with safe application-built progress."""
from typing import Any

MESSAGES = {
    'input_invalid': 'Documentation preview inputs are invalid or unsupported',
    'snapshot_changed': 'Documentation inspection snapshot or selected input changed',
    'input_limit': 'Documentation preview input exceeds its explicit budget',
    'live_disabled': 'Paid documentation preview requires both the operator gate and explicit per-task permission',
    'maintenance_stopped': 'Documentation maintenance stopped at its ownership, pause or budget boundary',
    'model_failed': 'Documentation preview model request failed',
    'ownership_lost': 'Documentation execution ownership was revoked',
}


class DocumentationError(Exception):
    def __init__(self, code: str, *, result: dict[str, Any] | None = None,
                 metadata: dict[str, Any] | None = None) -> None:
        self.code = code if code in MESSAGES else 'input_invalid'
        self.result = result
        self.metadata = metadata or {}
        super().__init__(MESSAGES[self.code])
