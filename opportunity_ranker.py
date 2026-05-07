"""
Opportunity Ranker — Blends ML + News + Arbitrage + Volume + TradingAgents
===========================================================================
Produces a unified opportunity_score in [0, 1].
Score > 0.65 = actionable signal.

Formula:
  opportunity_score =
    ml_confidence          × 0.35   (existing quant engine signal)
    ta_score_normalised    × 0.25   (TradingAgents multi-agent LLM, -1→+1 to 0→1)
    news_score_normalised  × 0.15   (-1→+1 mapped to 0→1)
    arb_factor             × 0.15   (net_spread / 0.5%, capped at 1.0)
    volume_factor          × 0.10   ((vol_ratio - 1) / 2, capped at 1.0)

TradingAgents is opt-in via ENABLE_TRADING_AGENTS=true in .env.
When disabled, its weight is redistributed to ML and news.
"""

import os
from dotenv import load_dotenv
load_dotenv()

OPPORTUNITY_THRESHOLD = 0.65

ENABLE_TA = os.getenv("ENABLE_TRADING_AGENTS", "false").lower() == "true"

# Weights — with TradingAgents
W_ML    = 0.35
W_TA    = 0.25
W_NEWS  = 0.15
W_ARB   = 0.15
W_VOL   = 0.10

# Weights — without TradingAgents (redistribute TA weight to ML and news)
W_ML_NOTA   = 0.45
W_NEWS_NOTA = 0.25
W_ARB_NOTA  = 0.20
W_VOL_NOTA  = 0.10


def compute_opportunity_score(
    ml_confidence: float,
    ml_action: str,
    news_score: float,       # -1.0 to +1.0
    arb_net_spread: float,   # percent, e.g. 0.45
    volume_ratio: float,     # current_vol / avg_vol, e.g. 1.8
    ta_score: float = None,  # TradingAgents score: -1.0 to +1.0 (None = not available)
) -> dict:
    """
    ml_action: "BUY" or "SELL" — used to align news and TA direction.
    Returns {opportunity_score, components, is_actionable}.
    """
    # Normalise news score from [-1,+1] to [0,1]
    news_normalised = (news_score + 1.0) / 2.0

    # If ML says SELL, invert directional signals so bearish = supportive
    if ml_action == "SELL":
        news_normalised = 1.0 - news_normalised

    # Arbitrage factor: 0.5% net = 1.0 factor (capped)
    arb_factor = min(max(arb_net_spread / 0.5, 0.0), 1.0)

    # Volume factor: 3× average volume = 1.0 factor (capped)
    vol_factor = min(max((volume_ratio - 1.0) / 2.0, 0.0), 1.0)

    # Clip ml_confidence to [0,1]
    ml_conf = min(max(float(ml_confidence), 0.0), 1.0)

    use_ta = ta_score is not None and ENABLE_TA

    if use_ta:
        # Normalise TA score [-1,+1] → [0,1]
        ta_normalised = (float(ta_score) + 1.0) / 2.0
        if ml_action == "SELL":
            ta_normalised = 1.0 - ta_normalised

        score = (
            ml_conf        * W_ML   +
            ta_normalised  * W_TA   +
            news_normalised * W_NEWS +
            arb_factor      * W_ARB  +
            vol_factor      * W_VOL
        )
        components = {
            "ml_confidence":   round(ml_conf, 4),
            "ta_normalised":   round(ta_normalised, 4),
            "news_normalised": round(news_normalised, 4),
            "arb_factor":      round(arb_factor, 4),
            "vol_factor":      round(vol_factor, 4),
            "weights":         "ML×0.35 + TA×0.25 + news×0.15 + arb×0.15 + vol×0.10",
        }
    else:
        score = (
            ml_conf         * W_ML_NOTA   +
            news_normalised * W_NEWS_NOTA +
            arb_factor      * W_ARB_NOTA  +
            vol_factor      * W_VOL_NOTA
        )
        components = {
            "ml_confidence":   round(ml_conf, 4),
            "ta_normalised":   None,
            "news_normalised": round(news_normalised, 4),
            "arb_factor":      round(arb_factor, 4),
            "vol_factor":      round(vol_factor, 4),
            "weights":         "ML×0.45 + news×0.25 + arb×0.20 + vol×0.10 (TA disabled)",
        }

    score = round(min(max(score, 0.0), 1.0), 4)

    return {
        "opportunity_score": score,
        "is_actionable": score > OPPORTUNITY_THRESHOLD,
        "components": components,
    }


def rank_opportunities(opportunities: list) -> list:
    """Sort list of opportunity dicts by score desc, return actionable first."""
    return sorted(opportunities, key=lambda x: -x.get("opportunity_score", 0))


if __name__ == "__main__":
    print(f"\nOpportunity Ranker — ENABLE_TRADING_AGENTS={ENABLE_TA}")
    print("=" * 75)

    tests = [
        # Strong BUY: high ML, bullish TA, bullish news, some arb, high volume
        dict(ml_confidence=0.78, ml_action="BUY",  news_score=0.6,  arb_net_spread=0.3,  volume_ratio=2.5, ta_score=0.7),
        # TA disagrees with ML: ML=BUY but TA=sell
        dict(ml_confidence=0.72, ml_action="BUY",  news_score=0.2,  arb_net_spread=0.1,  volume_ratio=1.5, ta_score=-0.5),
        # Weak signal: medium ML, neutral everything
        dict(ml_confidence=0.55, ml_action="BUY",  news_score=0.0,  arb_net_spread=0.0,  volume_ratio=1.0, ta_score=0.0),
        # Strong SELL with TA confirmation
        dict(ml_confidence=0.72, ml_action="SELL", news_score=-0.5, arb_net_spread=0.1,  volume_ratio=1.8, ta_score=-0.7),
        # No TA data (disabled/unavailable)
        dict(ml_confidence=0.78, ml_action="BUY",  news_score=0.6,  arb_net_spread=0.3,  volume_ratio=2.5, ta_score=None),
    ]

    labels = ["Strong BUY+TA", "TA disagrees", "Weak signal", "SELL+TA", "No TA"]
    print(f"\n  {'Case':<18} {'Score':>8} {'Act':>6}  Components")
    print("  " + "-" * 70)
    for label, t in zip(labels, tests):
        r = compute_opportunity_score(**t)
        c = r["components"]
        ta_str = f"ta={c['ta_normalised']:.2f}" if c["ta_normalised"] is not None else "ta=N/A"
        print(f"  {label:<18} {r['opportunity_score']:>8.4f} {'YES' if r['is_actionable'] else 'no':>6}  "
              f"ml={c['ml_confidence']:.2f} {ta_str} "
              f"news={c['news_normalised']:.2f} "
              f"arb={c['arb_factor']:.2f} "
              f"vol={c['vol_factor']:.2f}")
    print()
