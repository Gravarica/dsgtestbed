from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd

from tables import BATCH_COUNT, customer_table, order_batch


@dataclass
class Tables:
    customers: pd.DataFrame
    order_batches: List[pd.DataFrame]


def init_worker(cfg) -> Tables:
    return Tables(
        customers=customer_table(int(cfg.group_count)),
        order_batches=[order_batch(batch_index, int(cfg.data_quality)) for batch_index in range(BATCH_COUNT)],
    )


def process(item, cfg, tables: Tables) -> pd.DataFrame:
    orders = tables.order_batches[item.sample_index]
    joined = orders.merge(tables.customers, on="customer_id", how="inner")
    joined["total"] = joined["quantity"] * joined["unit_price"] * (1.0 - joined["discount"])
    return (
        joined.groupby("group")
        .agg(
            order_count=("total", "size"),
            quantity=("quantity", "sum"),
            revenue=("total", "sum"),
            mean_order=("total", "mean"),
            customers=("customer_id", "nunique"),
        )
        .reset_index()
    )
