import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

import service
import tables
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_DATA_QUALITY = 100000
DEFAULT_GROUP_COUNT = 1000


def configured(data_quality=DEFAULT_DATA_QUALITY, group_count=DEFAULT_GROUP_COUNT):
    return SimpleNamespace(data_quality=data_quality, group_count=group_count, service_directory=SERVICE_DIRECTORY)


def result_for(prepared, sample_index, cfg):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, prepared)


def reference_totals(orders: pd.DataFrame, customers: pd.DataFrame, group_count: int):
    customer_ids = orders["customer_id"].to_numpy()
    known = customer_ids < tables.CUSTOMER_COUNT
    groups = customers["group"].to_numpy()[customer_ids[known]]
    discounts = customers["discount"].to_numpy()[customer_ids[known]]
    totals = orders["quantity"].to_numpy()[known] * orders["unit_price"].to_numpy()[known] * (1.0 - discounts)
    return (
        np.bincount(groups, minlength=group_count),
        np.bincount(groups, weights=totals, minlength=group_count),
        int(known.sum()),
    )


def test_proof():
    cfg = configured()
    prepared = service.init_worker(cfg)
    assert len(prepared.order_batches) == tables.BATCH_COUNT
    for sample_index, orders in enumerate(prepared.order_batches):
        result = result_for(prepared, sample_index, cfg)
        counts, revenues, known_orders = reference_totals(orders, prepared.customers, DEFAULT_GROUP_COUNT)
        assert known_orders < len(orders)
        assert int(result["order_count"].sum()) == known_orders
        present = np.flatnonzero(counts)
        assert result["group"].to_numpy().tolist() == present.tolist()
        assert result["order_count"].to_numpy().tolist() == counts[present].tolist()
        assert np.allclose(result["revenue"].to_numpy(), revenues[present], rtol=1e-9)
        assert np.allclose(result["mean_order"].to_numpy(), revenues[present] / counts[present], rtol=1e-9)


def test_data_quality_knob_sets_how_many_orders_each_batch_holds():
    small = service.init_worker(configured(data_quality=1000))
    large = service.init_worker(configured(data_quality=1000000))
    assert len(small.order_batches[0]) == 1000
    assert len(large.order_batches[0]) == 1000000
    assert result_for(small, 0, configured(data_quality=1000))["order_count"].sum() < result_for(
        large, 0, configured(data_quality=1000000)
    )["order_count"].sum()


def test_group_count_knob_sets_how_many_groups_the_totals_are_split_into():
    few = service.init_worker(configured(group_count=10))
    many = service.init_worker(configured(group_count=5000))
    assert len(result_for(few, 0, configured(group_count=10))) == 10
    assert len(result_for(many, 0, configured(group_count=5000))) > 4000
    assert set(few.customers["group"]) == set(range(10))


def test_process_returns_a_table_with_one_row_per_group():
    prepared = service.init_worker(configured())
    result = result_for(prepared, 0, configured())
    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == ["group", "order_count", "quantity", "revenue", "mean_order", "customers"]
    assert result["group"].is_unique


def test_the_same_batch_is_generated_every_time():
    first = tables.order_batch(3, 5000)
    second = tables.order_batch(3, 5000)
    pd.testing.assert_frame_equal(first, second)
