"""
app/core/enum.py
ACTION REQUIRED: Merge the NEW block below into your existing enum.py.
Keep all your existing enums untouched above the divider.
"""
import enum

# ── YOUR EXISTING ENUMS STAY HERE ─────────────────────────────────────────────


# ── NEW: EW Track & Activity Report (schema v5.0) ─────────────────────────────

class ClassificationType(str, enum.Enum):
    UNCLASSIFIED   = "UNCLASSIFIED"
    CUI            = "CUI"
    CONFIDENTIAL   = "CONFIDENTIAL"
    SECRET         = "SECRET"
    TOP_SECRET     = "TOP_SECRET"


class SignalType(str, enum.Enum):
    RADAR                 = "radar"
    RADAR_PULSE           = "radar_pulse"
    RADAR_CONTINUOUS_WAVE = "radar_continuous_wave"
    COMMUNICATION         = "communication"
    UNKNOWN               = "unknown"


class HostilityType(str, enum.Enum):
    FRIENDLY          = "friendly"
    HOSTILE           = "hostile"
    NEUTRAL           = "neutral"
    UNKNOWN           = "unknown"
    AMBIGUOUS_SUSPECT = "ambiguous_suspect"
    NO_LIBRARY_MATCH  = "no_library_match"


class PlatformCategoryType(str, enum.Enum):
    AIRCRAFT   = "aircraft"
    LAND       = "land"
    SENSOR     = "sensor"
    SUBSURFACE = "subsurface"
    SURFACE    = "surface"
    WEAPON     = "weapon"
    UNKNOWN    = "unknown"


class SensorRoleType(str, enum.Enum):
    ORIGIN  = "origin"
    CONFIRM = "confirm"
    AUGMENT = "augment"
