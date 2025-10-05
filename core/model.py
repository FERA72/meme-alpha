# core/model.py
import pickle
import os

_model = None


def _load():
    global _model
    if _model is None and os.path.exists("model.pkl"):
        with open("model.pkl", "rb") as f:
            _model = pickle.load(f)
    return _model


def model_score_proba(closes_1d):
    """
    closes_1d: numpy array or list of recent close prices
    returns: float probability (0..1) or None if no model
    """
    m = _load()
    if m is None:
        return None
    import numpy as np
    x = np.array(closes_1d[-60:], dtype=float)  # last 60 closes
    # very simple feature: normalized differences; replace with your features later
    feats = (x[1:] - x[:-1]) / (x[:-1] + 1e-9)
    feats = feats[-30:]  # last 30 diffs
    if len(feats) < 30:
        feats = np.pad(feats, (30-len(feats), 0))
    proba = float(m.predict_proba([feats])[0][1])
    return proba
