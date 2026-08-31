from __future__ import annotations


INDICATORS = {
    "yield_gap": {
        "label": "Yield gap",
        "short_label": "Yield gap",
        "description": "Estimated gap between attainable and current rice yield.",
        "unit": "priority index",
        "colour": "#d97706",
    },
    "drought_risk": {
        "label": "Drought risk",
        "short_label": "Drought",
        "description": "Relative exposure and sensitivity to seasonal drought.",
        "unit": "risk index",
        "colour": "#c2410c",
    },
    "flood_risk": {
        "label": "Flood risk",
        "short_label": "Flood",
        "description": "Relative exposure and sensitivity to flooding.",
        "unit": "risk index",
        "colour": "#2563eb",
    },
    "poverty_index": {
        "label": "Poverty and vulnerability",
        "short_label": "Vulnerability",
        "description": "Synthetic proxy for livelihood vulnerability and equity need.",
        "unit": "need index",
        "colour": "#7c3aed",
    },
    "irrigation_gap": {
        "label": "Irrigation access gap",
        "short_label": "Irrigation gap",
        "description": "Relative lack of access to reliable irrigation.",
        "unit": "gap index",
        "colour": "#0891b2",
    },
    "market_isolation": {
        "label": "Market isolation",
        "short_label": "Isolation",
        "description": "Synthetic proxy for travel-time and market-access disadvantage.",
        "unit": "need index",
        "colour": "#475569",
    },
    "nbs_opportunity": {
        "label": "Nature-based solutions opportunity",
        "short_label": "NbS opportunity",
        "description": "Relative opportunity for landscape restoration and water measures.",
        "unit": "opportunity index",
        "colour": "#15803d",
    },
}


SCENARIOS = {
    "balanced": {
        "label": "Balanced resilience",
        "description": "Balances production, climate exposure, equity and implementation need.",
        "weights": {
            "yield_gap": 0.22,
            "drought_risk": 0.18,
            "flood_risk": 0.12,
            "poverty_index": 0.14,
            "irrigation_gap": 0.12,
            "market_isolation": 0.08,
            "nbs_opportunity": 0.14,
        },
    },
    "productivity": {
        "label": "Productivity first",
        "description": "Emphasises yield gap and irrigation constraints.",
        "weights": {
            "yield_gap": 0.38,
            "drought_risk": 0.12,
            "flood_risk": 0.08,
            "poverty_index": 0.08,
            "irrigation_gap": 0.22,
            "market_isolation": 0.04,
            "nbs_opportunity": 0.08,
        },
    },
    "climate": {
        "label": "Climate resilience",
        "description": "Emphasises drought, flood and nature-based solutions opportunity.",
        "weights": {
            "yield_gap": 0.12,
            "drought_risk": 0.26,
            "flood_risk": 0.20,
            "poverty_index": 0.10,
            "irrigation_gap": 0.10,
            "market_isolation": 0.04,
            "nbs_opportunity": 0.18,
        },
    },
    "equity": {
        "label": "Equity and reach",
        "description": "Emphasises vulnerability, isolation and underserved areas.",
        "weights": {
            "yield_gap": 0.14,
            "drought_risk": 0.12,
            "flood_risk": 0.10,
            "poverty_index": 0.28,
            "irrigation_gap": 0.12,
            "market_isolation": 0.16,
            "nbs_opportunity": 0.08,
        },
    },
}

