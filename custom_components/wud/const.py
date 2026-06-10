"""Constants for the What's Up Docker integration."""

DOMAIN = "wud"

CONF_URL = "url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 300  # seconds (5 minutes)
MIN_SCAN_INTERVAL = 60  # seconds (1 minute)
MAX_SCAN_INTERVAL = 86400  # seconds (24 hours)

CONF_VERIFY_SSL = "verify_ssl"
DEFAULT_VERIFY_SSL = True

TRIGGER_TYPES_UPDATER = frozenset({"docker", "compose", "dockercompose"})
