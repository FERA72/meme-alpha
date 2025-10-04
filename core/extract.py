# core/extract.py
def mints_from_tx(tx):
    """
    Return *all* SPL mint addresses seen in postTokenBalances for a transaction.
    """
    out = set()
    if not tx:
        return out
    post = tx.get("meta", {}).get("postTokenBalances") or []
    for b in post:
        mint = b.get("mint")
        if mint:
            out.add(mint)
    return out
