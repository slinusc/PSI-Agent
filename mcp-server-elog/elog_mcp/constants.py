"""
ELOG Filter Constants
=====================

Complete list of valid filter values for SwissFEL ELOG.
Use these constants to ensure correct filter values in your queries.
"""

# ============================================================================
# CATEGORIES
# ============================================================================

CATEGORIES = [
    "Info",
    "Problem",
    "Pikett",
    "Access",
    "Measurement summary",
    "Shift summary",
    "Tipps & Tricks",
    "Überbrückung",
    "Schicht-Auftrag",
    "RC exchange minutes",
    "Weekly reference settings",
    "Schicht-Übergabe",
    "DCM minutes",
    "Laser- & Gun-Performance Routine",
    "Seed laser operation"
]

# Common category groups
INCIDENT_CATEGORIES = ["Problem", "Pikett"]
SUMMARY_CATEGORIES = ["Shift summary", "Schicht-Übergabe", "Measurement summary"]
PROCEDURE_CATEGORIES = ["Tipps & Tricks", "Überbrückung"]
MEETING_CATEGORIES = ["RC exchange minutes", "DCM minutes"]

# ============================================================================
# SYSTEMS
# ============================================================================

SYSTEMS = [
    "Beamdynamics",
    "Controls",
    "Diagnostics",
    "Electric supply",
    "Feedbacks",
    "Insertion-devices",
    "Laser",
    "Magnet Power Supplies",
    "Operation",
    "Photonics",
    "PLC",
    "RF",
    "Safety",
    "Timing & Sync",
    "Vacuum",
    "Water cooling & Ventilation",
    "Other",
    "Unknown"
]

# Critical systems
CRITICAL_SYSTEMS = ["RF", "Controls", "Safety", "Feedbacks"]

# ============================================================================
# DOMAINS
# ============================================================================

DOMAINS = [
    "Injector",
    "Linac1",
    "Linac2",
    "Linac3",
    "Aramis",
    "Aramis Beamlines",
    "Athos",
    "Athos Beamlines",
    "Global"
]

# Accelerator sections
LINAC_DOMAINS = ["Linac1", "Linac2", "Linac3"]
FEL_DOMAINS = ["Aramis", "Athos"]
BEAMLINE_DOMAINS = ["Aramis Beamlines", "Athos Beamlines"]

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def validate_filter(filter_name: str, filter_value: str) -> bool:
    """
    Validate that a filter value is in the allowed list.

    Args:
        filter_name: "Category", "System", or "Domain"
        filter_value: Value to validate

    Returns:
        True if valid, False otherwise
    """
    mapping = {
        "Category": CATEGORIES,
        "System": SYSTEMS,
        "Domain": DOMAINS
    }

    allowed_values = mapping.get(filter_name)
    if not allowed_values:
        return False

    return filter_value in allowed_values


def get_filter_values(filter_name: str) -> list:
    """
    Get all valid values for a filter.

    Args:
        filter_name: "Category", "System", or "Domain"

    Returns:
        List of valid values
    """
    mapping = {
        "Category": CATEGORIES,
        "System": SYSTEMS,
        "Domain": DOMAINS
    }

    return mapping.get(filter_name, [])


# ============================================================================
# EXAMPLE FILTER PRESETS
# ============================================================================

FILTER_PRESETS = {
    # Incidents
    "recent_problems": {
        "Category": "Problem"
    },
    "safety_issues": {
        "Category": "Problem",
        "System": "Safety"
    },
    "rf_problems": {
        "Category": "Problem",
        "System": "RF"
    },

    # Summaries
    "shift_summaries": {
        "Category": "Shift summary"
    },
    "german_shift_summaries": {
        "Category": "Schicht-Übergabe"
    },

    # Domain-specific
    "injector_issues": {
        "Category": "Problem",
        "Domain": "Injector"
    },
    "aramis_operations": {
        "Domain": "Aramis"
    },
    "athos_operations": {
        "Domain": "Athos"
    },

    # System-specific
    "rf_system": {
        "System": "RF"
    },
    "controls_system": {
        "System": "Controls"
    },
    "diagnostics_system": {
        "System": "Diagnostics"
    },

    # Performance
    "performance_checks": {
        "Category": "Laser- & Gun-Performance Routine"
    },

    # Meetings
    "rc_minutes": {
        "Category": "RC exchange minutes"
    }
}


def get_preset(preset_name: str) -> dict:
    """
    Get a predefined filter preset.

    Args:
        preset_name: Name of the preset

    Returns:
        Filter dictionary
    """
    return FILTER_PRESETS.get(preset_name, {})


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("ELOG Filter Constants")
    print("=" * 80)

    print(f"\nCategories ({len(CATEGORIES)}):")
    for cat in CATEGORIES:
        print(f"  - {cat}")

    print(f"\nSystems ({len(SYSTEMS)}):")
    for sys in SYSTEMS:
        print(f"  - {sys}")

    print(f"\nDomains ({len(DOMAINS)}):")
    for dom in DOMAINS:
        print(f"  - {dom}")

    print(f"\nFilter Presets ({len(FILTER_PRESETS)}):")
    for name, filters in FILTER_PRESETS.items():
        print(f"  - {name}: {filters}")

    print("\n" + "=" * 80)
    print("Validation Examples")
    print("=" * 80)

    # Test validation
    test_cases = [
        ("Category", "Problem", True),
        ("Category", "problem", False),  # Case sensitive
        ("System", "RF", True),
        ("System", "Laser", True),
        ("Domain", "Aramis", True),
        ("Domain", "InvalidDomain", False)
    ]

    for filter_name, value, expected in test_cases:
        result = validate_filter(filter_name, value)
        status = "✓" if result == expected else "✗"
        print(f"{status} validate_filter('{filter_name}', '{value}') = {result} (expected: {expected})")
