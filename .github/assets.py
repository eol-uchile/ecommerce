from .base import *
from path import Path

# Enable themes
COMPREHENSIVE_THEME_DIRS = [
    Path(DJANGO_ROOT + "/themes"),
]
ENABLE_COMPREHENSIVE_THEMING = True
DEFAULT_SITE_THEME = 'openuchile'

# Compress
COMPRESS_ENABLED = True
COMPRESS_OFFLINE = True
COMPRESS_ROOT = STATIC_ROOT
# Minify CSS
# Note: COMPRESS_CSS_FILTERS has been replaced with COMPRESS_FILTERS in django-compressor,
# but replacing the settings name gives an error during compression in github test-python build check
# See info here: https://github.com/django-compressor/django-compressor/issues/985
COMPRESS_CSS_FILTERS += [
    'compressor.filters.cssmin.CSSMinFilter',
]

# Static serve
try:
    idx = MIDDLEWARE.index('django.middleware.security.SecurityMiddleware')
    MIDDLEWARE = MIDDLEWARE[:idx] + ('whitenoise.middleware.WhiteNoiseMiddleware',) + MIDDLEWARE[idx:]
except:
    MIDDLEWARE = ('whitenoise.middleware.WhiteNoiseMiddleware',) + MIDDLEWARE
STATICFILES_STORAGE= 'whitenoise.storage.CompressedStaticFilesStorage'

# Change syslog-based loggers which don't work inside docker containers
LOGGING['handlers']['local'] = {'class': 'logging.NullHandler'}
LOGGING['handlers']['console']['level'] = 'DEBUG'
