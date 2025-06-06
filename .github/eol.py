from .production import *

# Static serve with WhiteNoise middleware
try:
    idx = MIDDLEWARE.index('django.middleware.security.SecurityMiddleware')
    MIDDLEWARE = MIDDLEWARE[:idx] + ('whitenoise.middleware.WhiteNoiseMiddleware',) + MIDDLEWARE[idx:]
except:
    MIDDLEWARE = ('whitenoise.middleware.WhiteNoiseMiddleware',) + MIDDLEWARE
STATICFILES_STORAGE= 'whitenoise.storage.CompressedStaticFilesStorage'

# Change syslog-based loggers which don't work inside docker containers
LOGGING['handlers']['local'] = {'class': 'logging.NullHandler'}
LOGGING['handlers']['console']['level'] = 'DEBUG'
