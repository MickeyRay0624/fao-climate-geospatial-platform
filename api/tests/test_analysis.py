from app.analysis import calculate_priorities, normalise_weights


def test_normalise_weights_fills_missing_indicators() -> None:
    weights = normalise_weights({"yield_gap": 2, "drought_risk": 1})

    assert round(sum(weights.values()), 8) == 1
    assert weights["yield_gap"] == 2 / 3
    assert weights["flood_risk"] == 0


def test_priority_ranking_and_rice_area_constraint() -> None:
    template = {
        "province": "Demo",
        "population": 1000,
        "data_quality": 0.9,
        "geometry": {"type": "MultiPolygon", "coordinates": []},
    }
    areas = [
        {
            **template,
            "id": 1,
            "code": "A",
            "name": "A",
            "rice_area_ha": 1200,
            "indicators": {
                "yield_gap": 0.9,
                "drought_risk": 0.8,
                "flood_risk": 0.7,
                "poverty_index": 0.6,
                "irrigation_gap": 0.7,
                "market_isolation": 0.4,
                "nbs_opportunity": 0.8,
            },
        },
        {
            **template,
            "id": 2,
            "code": "B",
            "name": "B",
            "rice_area_ha": 500,
            "indicators": {code: 1.0 for code in normalise_weights({"yield_gap": 1})},
        },
    ]

    results = calculate_priorities(areas, {"yield_gap": 1}, min_rice_area_ha=750)

    assert results[0]["code"] == "A"
    assert results[0]["rank"] == 1
    assert results[1]["eligible"] is False
    assert results[1]["priority_band"] == "Not eligible"


def test_missing_indicator_is_disclosed() -> None:
    values = {code: 0.5 for code in normalise_weights({"yield_gap": 1})}
    values["yield_gap"] = None
    results = calculate_priorities(
        [
            {
                "id": 1,
                "code": "A",
                "name": "A",
                "province": "Demo",
                "population": 1000,
                "rice_area_ha": 1000,
                "data_quality": 0.8,
                "geometry": {"type": "MultiPolygon", "coordinates": []},
                "indicators": values,
            }
        ],
        {"yield_gap": 1},
        min_rice_area_ha=0,
    )

    assert results[0]["missing_indicators"] == ["yield_gap"]
    assert results[0]["data_completeness"] < 1

