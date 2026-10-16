"""Nested chart layout: dashboard → tier → view → timeline → chart name → chart_id.

Auto-generated from ``view_catalog.CHART_CATALOG``. SQL builders are keyed by
stable ``chart_id`` + timeline so metadata display-name changes do not break lookup.

Regenerate::

    python3 generate_queries_file.py
"""

from __future__ import annotations

CHART_REGISTRY: dict[str, dict[str, dict[str, dict[str, dict[str, str]]]]] = {
    "proof-points": {
        "ccd": {
            "quality": {
                "yoy": {
                    "Groups Meeting Board Cert. Criteria": "15",
                    "Groups Meeting EBM Criteria": "19",
                    "Groups Meeting External Quality Certification Criteria": "17",
                    "Providers having Board Certification": "16",
                    "Providers having EBM Opportunities": "20",
                    "Providers having External Quality Certification": "18"
                },
                "ytd": {
                    "Groups Meeting Board Cert. Criteria": "15",
                    "Groups Meeting EBM Criteria": "19",
                    "Groups Meeting External Quality Certification Criteria": "17",
                    "Providers having Board Certification": "16",
                    "Providers having EBM Opportunities": "20",
                    "Providers having External Quality Certification": "18"
                }
            },
            "savings": {
                "yoy": {
                    "Episode Savings": "14",
                    "Gross Savings": "13"
                },
                "ytd": {
                    "Episode Savings": "14",
                    "Gross Savings": "13"
                }
            },
            "spend": {
                "yoy": {
                    "Gross Episode Counts": "4",
                    "Gross Episode Spend": "3",
                    "High-Cost Drugs Spend": "7",
                    "Medical Category Spend": "5",
                    "Per Episode Spend": "8",
                    "Pharmacy Category Spend": "6"
                },
                "ytd": {
                    "Gross Episode Counts": "4",
                    "Gross Episode Spend": "3",
                    "High-Cost Drugs Spend": "7",
                    "Medical Category Spend": "5",
                    "Per Episode Spend": "8",
                    "Pharmacy Category Spend": "6"
                }
            },
            "turnover-disruption": {
                "yoy": {
                    "Member-to-Provider Relationships": "22",
                    "Provider Turnover": "21"
                },
                "ytd": {
                    "Member-to-Provider Relationships": "22",
                    "Provider Turnover": "21"
                }
            },
            "utilization": {
                "yoy": {
                    "Claim Count": "11",
                    "Claim Procedure Count": "12",
                    "Client Visits": "10",
                    "Member Visits": "9"
                },
                "ytd": {
                    "Claim Count": "11",
                    "Claim Procedure Count": "12",
                    "Client Visits": "10",
                    "Member Visits": "9"
                }
            },
            "volume": {
                "yoy": {
                    "Provider Group Volume": "1",
                    "Provider Volume": "2"
                },
                "ytd": {
                    "Provider Group Volume": "1",
                    "Provider Volume": "2"
                }
            }
        },
        "tier-1": {
            "quality": {
                "yoy": {
                    "Groups Meeting Board Cert. Criteria": "115",
                    "Groups Meeting EBM Criteria": "119",
                    "Groups Meeting External Quality Certification Criteria": "117",
                    "Providers having Board Certification": "116",
                    "Providers having EBM Opportunities": "120",
                    "Providers having External Quality Certification": "118"
                },
                "ytd": {
                    "Groups Meeting Board Cert. Criteria": "115",
                    "Groups Meeting EBM Criteria": "119",
                    "Groups Meeting External Quality Certification Criteria": "117",
                    "Providers having Board Certification": "116",
                    "Providers having EBM Opportunities": "120",
                    "Providers having External Quality Certification": "118"
                }
            },
            "savings": {
                "yoy": {
                    "Episode Savings": "114",
                    "Gross Savings": "113"
                },
                "ytd": {
                    "Episode Savings": "114",
                    "Gross Savings": "113"
                }
            },
            "spend": {
                "yoy": {
                    "Gross Episode Counts": "104",
                    "Gross Episode Spend": "103",
                    "High-Cost Drugs Spend": "107",
                    "Medical Category Spend": "105",
                    "Per Episode Spend": "108",
                    "Pharmacy Category Spend": "106"
                },
                "ytd": {
                    "Gross Episode Counts": "104",
                    "Gross Episode Spend": "103",
                    "High-Cost Drugs Spend": "107",
                    "Medical Category Spend": "105",
                    "Per Episode Spend": "108",
                    "Pharmacy Category Spend": "106"
                }
            },
            "turnover-disruption": {
                "yoy": {
                    "Member-to-Provider Relationships": "122",
                    "Provider Turnover": "121"
                },
                "ytd": {
                    "Member-to-Provider Relationships": "122",
                    "Provider Turnover": "121"
                }
            },
            "utilization": {
                "yoy": {
                    "Claim Count": "111",
                    "Claim Procedure Count": "112",
                    "Client Visits": "110",
                    "Member Visits": "109"
                },
                "ytd": {
                    "Claim Count": "111",
                    "Claim Procedure Count": "112",
                    "Client Visits": "110",
                    "Member Visits": "109"
                }
            },
            "volume": {
                "yoy": {
                    "Provider Group Volume": "101",
                    "Provider Volume": "102"
                },
                "ytd": {
                    "Provider Group Volume": "101",
                    "Provider Volume": "102"
                }
            }
        }
    }
}
