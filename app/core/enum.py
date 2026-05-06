"""
app/core/enum.py
ACTION REQUIRED: Merge the NEW block below into your existing enum.py.
Keep all your existing enums untouched above the divider.
"""
import enum

# ── YOUR EXISTING ENUMS STAY HERE ─────────────────────────────────────────────


# ── NEW: EW Track & Activity Report (schema v5.0) ─────────────────────────────

class Classification(str, enum.Enum):
    UNCLASSIFIED   = "UNCLASSIFIED"
    CUI            = "CUI"
    CONFIDENTIAL   = "CONFIDENTIAL"
    SECRET         = "SECRET"
    TOP_SECRET     = "TOP_SECRET"


class SignalType(str, enum.Enum):
    RADAR                 = "RADAR"
    RADAR_PULSE           = "RADAR_PULSE"
    RADAR_CONTINUOUS_WAVE = "RADAR_CONTINUOUS_WAVE"
    COMMUNICATION         = "COMMUNICATION"
    UNKNOWN               = "UNKNOWN"


class HostilityType(str, enum.Enum):
    FRIENDLY          = "FRIENDLY"
    HOSTILE           = "HOSTILE"
    NEUTRAL           = "NEUTRAL"
    UNKNOWN           = "UNKNOWN"
    AMBIGUOUS_SUSPECT = "AMBIGUOUS_SUSPECT"
    NO_LIBRARY_MATCH  = "NO_LIBRARY_MATCH"


class PlatformCategoryType(str, enum.Enum):
    AIRCRAFT   = "AIRCRAFT"
    LAND       = "LAND"
    SENSOR     = "SENSOR"
    SUBSURFACE = "SUBSURFACE"
    SURFACE    = "SURFACE"
    WEAPON     = "WEAPON"
    UNKNOWN    = "UNKNOWN"


class SensorRoleType(str, enum.Enum):
    ORIGIN  = "ORIGIN"
    CONFIRM = "CONFIRM"
    AUGMENT = "AUGMENT"


class SensorType(str, enum.Enum):
    RADAR    = "RADAR"
    ELINT    = "ELINT"
    SIGINT   = "SIGINT"
    EO_IR    = "EO_IR"
    ACOUSTIC = "ACOUSTIC"
    OTHER    = "OTHER"


class SensorStatusType(str, enum.Enum):
    ACTIVE      = "ACTIVE"
    INACTIVE    = "INACTIVE"
    DEGRADED    = "DEGRADED"
    OFFLINE     = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"


class SensorSourceType(str, enum.Enum):
    MANUAL    = "MANUAL"
    AUTOMATED = "AUTOMATED"
    FEED      = "FEED"
    API       = "API"
