"""Constants for the What's Up Docker integration."""

DOMAIN = "wud"

CONF_URL = "url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"

CONF_AUTH_METHOD = "auth_method"
CONF_TOKEN = "token"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_OIDC_DISCOVERY_URL = "oidc_discovery_url"
CONF_OIDC_SCOPE = "oidc_scope"

AUTH_NONE = "none"
AUTH_BASIC = "basic"
AUTH_BEARER = "bearer"
AUTH_OIDC = "oidc"
AUTH_METHODS = (AUTH_NONE, AUTH_BASIC, AUTH_BEARER, AUTH_OIDC)
DEFAULT_AUTH_METHOD = AUTH_NONE
DEFAULT_OIDC_SCOPE = "openid"

# Refresh OIDC access tokens this many seconds before they expire.
OIDC_TOKEN_EXPIRY_MARGIN = 30

DEFAULT_SCAN_INTERVAL = 300  # seconds (5 minutes)
MIN_SCAN_INTERVAL = 60  # seconds (1 minute)
MAX_SCAN_INTERVAL = 86400  # seconds (24 hours)

CONF_VERIFY_SSL = "verify_ssl"
DEFAULT_VERIFY_SSL = True

TRIGGER_TYPES_UPDATER = frozenset({"docker", "compose", "dockercompose"})

INSTALL_TIMEOUT = 600  # seconds (10 minutes)
INSTALL_POLL_INTERVAL = 15  # seconds (15 seconds)
INSTALL_ESTIMATED_DURATION = 60  # seconds
PROGRESS_UPDATE_INTERVAL = 2  # seconds

# Cap the simulated progress at this percentage until completion is confirmed,
# so the bar never claims 100% before WUD reports the update is done.
PROGRESS_MAX_BEFORE_COMPLETE = 90

CONF_MAX_CONCURRENT_UPDATES = "max_concurrent_updates"
DEFAULT_MAX_CONCURRENT_UPDATES = 2  # 0 = unlimited

CONF_AUTO_UPDATE_TIME = "auto_update_time"
DEFAULT_AUTO_UPDATE_TIME = "05:00"

AUTO_UPDATE_NEVER = "never"
AUTO_UPDATE_IMMEDIATELY = "immediately"
AUTO_UPDATE_INTEGRATION_TIME = "integration_update_time"
AUTO_UPDATE_CONTAINER_TIME = "container_update_time"
