import pytest

from byteplan._todo import verifies


@verifies("ce72")
@pytest.mark.xfail(reason="BytePlan ce72: acceptance test not implemented", strict=True)
def test_task_ce72() -> None:
    """Acceptance test scaffold for BytePlan task ce72.

    Target: task ce72 (statement)
    Requirement: Summarize scan results by default instead of listing every annotation
    """
    # GIVEN: TODO - arrange the state this requirement depends on
    # WHEN: TODO - exercise the code task ce72 is about
    # THEN: TODO - assert the required result
    pytest.fail("BytePlan ce72: acceptance test not implemented")


@verifies("9c60")
@pytest.mark.xfail(reason="BytePlan 9c60: acceptance test not implemented", strict=True)
def test_task_9c60() -> None:
    """Acceptance test scaffold for BytePlan task 9c60.

    Target: task 9c60 (statement)
    Requirement: List only active missing tasks by default
    """
    # GIVEN: TODO - arrange the state this requirement depends on
    # WHEN: TODO - exercise the code task 9c60 is about
    # THEN: TODO - assert the required result
    pytest.fail("BytePlan 9c60: acceptance test not implemented")


@verifies("d45d")
@pytest.mark.xfail(reason="BytePlan d45d: acceptance test not implemented", strict=True)
def test_build_server_preview_test_scaffold_preview() -> None:
    """Acceptance test scaffold for BytePlan task d45d.

    Target: build_server.<locals>.preview_test_scaffold.<locals>.preview (function)
    Requirement: Return only the scaffolded test, not the whole target file
    """
    # GIVEN: TODO - arrange the state this requirement depends on
    # WHEN: TODO - call build_server.<locals>.preview_test_scaffold.<locals>.preview
    # THEN: TODO - assert the required result
    pytest.fail("BytePlan d45d: acceptance test not implemented")
