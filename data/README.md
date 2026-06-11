# Data directory

Place your 5-year, 1-minute, back-adjusted continuous contract files here:

```
data/ES.csv  data/NQ.csv  data/RTY.csv  data/GC.csv  data/6E.csv  data/6J.csv
```

Required columns (CSV or parquet): `timestamp,open,high,low,close,volume`.
Timestamps must be tz-aware or in US/Eastern. Bars outside each contract's
liquid RTH window (see `quant/contracts.py`) are dropped automatically.
