from .config import MAX_AGE_MIN


def score(m):
    liq = m["liq_usd"]
    mc = m["mcap_usd"] or 0
    age = m["age_min"]
    liq_pts = 40*min(liq/80000.0, 1.0)
    if mc == 0:
        mc_pts = 0
    elif mc < 100_000:
        mc_pts = 5*(mc/100_000.0)
    elif mc <= 2_500_000:
        mc_pts = 5+20*((mc-100_000)/2_400_000)
    else:
        mc_pts = max(0.0, 25-((mc-2_500_000)/2_500_000)*10)
    age_pts = 10 if age is None else max(0.0, 25*(1.0-(age/MAX_AGE_MIN)))
    ratio = (mc/liq) if (liq > 0 and mc > 0) else 9999
    ratio_pts = 10 if ratio < 20 else (
        6 if ratio < 40 else (3 if ratio < 60 else 0))
    total = round(liq_pts+mc_pts+age_pts+ratio_pts, 1)
    return total, {"liq": round(liq_pts, 1), "mc": round(mc_pts, 1), "age": round(age_pts, 1), "ratio": round(ratio_pts, 1)}
