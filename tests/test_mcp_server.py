import pytest

from byteplan._todo import verifies


@verifies("932b36")
@pytest.mark.xfail(reason="BytePlan 932b36: acceptance test not implemented", strict=True)
def test_errors_as_tool_errors() -> None:
    """Acceptance test scaffold for BytePlan task 932b36.

    Target: _errors_as_tool_errors (function)
    Requirement: Tell agents to restart the MCP server when the registry schema is newer than it
    """
    # GIVEN: TODO - arrange the state this requirement depends on
    # WHEN: TODO - call _errors_as_tool_errors
    # THEN: TODO - assert the required result
    pytest.fail("BytePlan 932b36: acceptance test not implemented")
