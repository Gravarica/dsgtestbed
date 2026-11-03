import pytest

from dsg.service_runtime.joins import Joins


def test_joins_answer_only_for_the_last_input_with_the_time_of_the_first():
    joins = Joins(3)
    assert joins.input_arrived("cam-0", 10) is None
    assert joins.input_arrived("cam-1", 12) is None
    assert joins.input_arrived("cam-0", 20) is None
    assert joins.input_arrived("cam-0", 30) == 10
    assert joins.still_waiting() == 1
    assert Joins(1).input_arrived("cam-0", 5) == 5
    with pytest.raises(ValueError):
        Joins(0)
