"""
Shared constants across all services.
"""

# API Version
API_VERSION = "v1"

# Queue names
QUEUE_QUERIES = "queries"
QUEUE_NOTIFICATIONS = "notifications"
QUEUE_INGESTION = "ingestion"

# Query status values (for reference)
QUERY_STATUS_QUEUED = "queued"
QUERY_STATUS_PROCESSING = "processing"
QUERY_STATUS_NEEDS_CHOICE = "needs_choice"
QUERY_STATUS_DONE = "done"
QUERY_STATUS_FAILED = "failed"

# Plan types
PLAN_FREE = "free"
PLAN_BASIC = "basic"
PLAN_PREMIUM = "premium"

# Default limits
DEFAULT_DAILY_QUERIES_FREE = 5
DEFAULT_MONTHLY_QUERIES_FREE = 50

# Confidence thresholds
OCR_CONFIDENCE_THRESHOLD = 70
RETRIEVAL_CONFIDENCE_THRESHOLD = 80
