from .config import MIN_LIQ_USD, MIN_MCAP_USD, MAX_AGE_MIN


def hard_filters(m):
    reasons = []
    liq = m["liq_usd"]
    mc = m["mcap_usd"] or 0
    age = m["age_min"]
    if liq < MIN_LIQ_USD:
        reasons.append(f"Low liq ${int(liq):,} < {int(MIN_LIQ_USD):,}")
    if mc and mc < MIN_MCAP_USD:
        reasons.append(f"Low mcap ${int(mc):,} < {int(MIN_MCAP_USD):,}")
    if age is not None and age > MAX_AGE_MIN:
        reasons.append(f"Too old {age:.1f}m > {MAX_AGE_MIN}m")
    if liq > 0 and mc > 0 and (mc/liq) > 80:
        reasons.append(f"FDV/Liq {mc/liq:.1f} too high")
    return (len(reasons) > 0, reasons)
