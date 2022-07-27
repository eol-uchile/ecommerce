from .production import *

# Change syslog-based loggers which don't work inside docker containers
LOGGING['handlers']['local'] = {'class': 'logging.NullHandler'}

""" 
LOGGING['formatters']['json'] = {
    '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
}

LOGGING['handlers']['json'] = {
    'level': 'INFO',
    'class': 'logging.StreamHandler',
    'formatter': 'json',
}

LOGGING['loggers']['']['handlers'] = ['json']
 #LOGGING['handlers']['local'] = {'class': 'logging.StreamHandler'}
""" 

COMPRESS_ENABLED = True
COMPRESS_OFFLINE = True
COMPRESS_ROOT = '/openedx/ecommerce/assets'

DEBUG=False

# Static serve
MIDDLEWARE += (
    'whitenoise.middleware.WhiteNoiseMiddleware',
)
#STATICFILES_STORAGE = 'whitenoise.storage.ManifestStaticFilesStorage'
# Use default STORAGE as explained in http://whitenoise.evans.io/en/stable/django.html#storage-troubleshoot
# STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'
STATIC_ROOT = '/openedx/ecommerce/assets'

# Themes
COMPREHENSIVE_THEME_DIRS = ["/openedx/ecommerce/ecommerce/themes", ]
ENABLE_COMPREHENSIVE_THEMING = True
