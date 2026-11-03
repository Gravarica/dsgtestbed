from __future__ import annotations

import numpy as np
import pandas as pd

CUSTOMER_COUNT = 100_000
BATCH_COUNT = 16
UNKNOWN_CUSTOMER_SHARE = 0.02
CUSTOMER_SEED = 20260926
FIRST_BATCH_SEED = 7000


def customer_table(group_count: int) -> pd.DataFrame:
    random = np.random.default_rng(CUSTOMER_SEED)
    groups = np.arange(CUSTOMER_COUNT, dtype=np.int32) % group_count
    random.shuffle(groups)
    return pd.DataFrame(
        {
            "customer_id": np.arange(CUSTOMER_COUNT, dtype=np.int32),
            "group": groups,
            "discount": random.choice(np.array([0.0, 0.05, 0.1, 0.2]), size=CUSTOMER_COUNT),
        }
    )


def order_batch(batch_index: int, row_count: int) -> pd.DataFrame:
    random = np.random.default_rng(FIRST_BATCH_SEED + batch_index)
    popular_customers = np.minimum((random.pareto(1.1, row_count) * 2000).astype(np.int64), CUSTOMER_COUNT - 1)
    customer_ids = np.where(
        random.random(row_count) < 0.5, popular_customers, random.integers(0, CUSTOMER_COUNT, row_count)
    )
    unknown = random.random(row_count) < UNKNOWN_CUSTOMER_SHARE
    customer_ids = np.where(unknown, CUSTOMER_COUNT + random.integers(0, 1000, row_count), customer_ids)
    return pd.DataFrame(
        {
            "customer_id": customer_ids.astype(np.int32),
            "quantity": random.integers(1, 20, row_count).astype(np.int16),
            "unit_price": np.round(random.lognormal(3.0, 1.0, row_count), 2),
        }
    )
