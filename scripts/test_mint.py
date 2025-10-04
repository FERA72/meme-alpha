# scripts/test_mint.py
import argparse
from core import market as mkt, scoring, notifier


def human(n):
    return f"${int(n):,}" if n else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mint", required=True,
                    help="SPL mint address of the token")
    ap.add_argument("--force-post", action="store_true",
                    help="Post to Discord even if score < 50")
    args = ap.parse_args()

    mk = mkt.fetch_market(args.mint)
    if not mk:
        print("No DexScreener data for that mint (yet).")
        return

    # pretend it's brand new
    if mk["age_min"] is None:
        mk["age_min"] = 0.1

    score, parts = scoring.score(mk)
    print(f"Symbol: {mk['symbol']}")
    print(f"Mint:   {mk['mint']}")
    print(
        f"Liq:    {human(mk['liq_usd'])}   MC: {human(mk['mcap_usd'])}   Age: {mk['age_min']:.2f}m")
    print(f"Score:  {score}  -> {parts}")

    if score >= 50 or args.force_post:
        notifier.post(mk, score, {
            "liq": parts["liq"], "mc": parts["mc"], "age": parts["age"], "ratio": parts["ratio"]
        })
        print("Posted (or DRY).")
    else:
        print("Not posted (score < 50). Use --force-post to send anyway.")


if __name__ == "__main__":
    main()
