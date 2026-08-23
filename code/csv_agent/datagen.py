from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd

def gen_sales(n=200, seed=42, dirty=False):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        region = rng.choice(["华东","华北","华南","西南"])
        channel = rng.choice(["线上","线下"])
        price = float(round(rng.uniform(10,500),2))
        discount = float(round(rng.normal(0.1,0.05),3))
        quantity = int(rng.integers(1,20))
        sales = price*quantity*(1-discount)
        row = {"order_id":f"O{i:04d}","region":region,"channel":channel,"price":price,"discount":discount,"quantity":quantity,"sales":round(float(sales),2)}
        if dirty:
            if i%11==0: row["quantity"]=None
            if i%17==0: row["price"]=None
            if i%23==0: row["sales"]=99999.0
        rows.append(row)
    return pd.DataFrame(rows)