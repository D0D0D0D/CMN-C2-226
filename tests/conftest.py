# CMN-C2-226 — shared test helpers

import pytest

from framework.schemas.agent_status import AgentStatus


@pytest.fixture
def is_error():
    """Status equality helper tolerant of enum vs .value forms (F-05)."""
    def _is_error(status) -> bool:
        return status in (AgentStatus.ERROR, AgentStatus.ERROR.value)
    return _is_error
