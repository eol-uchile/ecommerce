
from .base import *

LOGGING["handlers"]["local"] = {
    "class": "logging.handlers.WatchedFileHandler",
    "filename": "/var/log/ecommerce.log",
    "formatter": "standard",
}

# Enable themes
COMPREHENSIVE_THEME_DIRS = ["/openedx/ecommerce/ecommerce/themes", ]
ENABLE_COMPREHENSIVE_THEMING = True

# Compress
COMPRESS_ENABLED = True
COMPRESS_OFFLINE = True
COMPRESS_ROOT = '/openedx/ecommerce/assets'