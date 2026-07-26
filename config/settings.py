"""
Generated with django-lux 1.4.15.
Project name: dlux_control.
Generated on: 2026-07-23.
"""
import os
from pathlib import Path
import logging
from urllib.parse import urlparse
from csp.constants import SELF, UNSAFE_EVAL, UNSAFE_INLINE
from dlux.utils import get_project_version, get_secret, dlux_settings


WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

BASE_DIR = Path(__file__).resolve().parent.parent
BASE_URL = os.getenv("BASE_URL", "http://localhost")
BASE_HOSTNAME = urlparse(BASE_URL).hostname
ALLOWED_URLS = [
    url.strip()
    for url in os.getenv("ALLOWED_URLS", "").split(",")
    if url.strip()
]
ROOT_URLCONF = "config.urls"
# The Updates card reads DLUX_APP_VERSION (or a root VERSION file). This project
# retired VERSION for release-manifest.json, so point it at the manifest.
DLUX_APP_VERSION = get_project_version(BASE_DIR)
DLUX_SETUP_GUARD_ALLOWED_PREFIXES = ("/api/agent/v1/",)
DLUX_MIDDLEWARE = "fleet.middleware.AgentApiBoundaryMiddleware"

DEBUG = os.getenv("DEBUG_STATUS", "True").lower() == "true"


def required_production_secret(secret_name, env_name, development_default):
    value = get_secret(secret_name, env_name)
    if value:
        return value
    if DEBUG:
        return development_default
    raise RuntimeError(f"{env_name} is required when DEBUG_STATUS=False.")


SECRET_KEY = required_production_secret(
    "DJANGO_SECRET_KEY",
    "DJANGO_SECRET_KEY",
    "insecure-temporary-dev-only-key-change-me-now",
)

# Security & Origins configuration
is_secure = BASE_URL.startswith("https://")
is_local = BASE_HOSTNAME in ["localhost", "127.0.0.1"] or ":" in (BASE_HOSTNAME or "")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "web,nginx,localhost,127.0.0.1").split(",")
    if host.strip()
]

# Unified list of trusted origins for CORS and CSRF
TRUSTED_ORIGINS = list(set(
    ([BASE_URL] if BASE_URL.startswith(("http://", "https://")) else []) +
    ALLOWED_URLS +
    (['http://localhost', 'http://127.0.0.1'] if DEBUG else [])
))

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = TRUSTED_ORIGINS
CSRF_TRUSTED_ORIGINS = TRUSTED_ORIGINS

SESSION_COOKIE_SECURE = is_secure
CSRF_COOKIE_SECURE = is_secure
SESSION_COOKIE_DOMAIN = None if is_local else BASE_HOSTNAME
CSRF_COOKIE_DOMAIN = None if is_local else BASE_HOSTNAME

if DEBUG:
    logging.basicConfig(level=logging.DEBUG)
else:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURE_SSL_REDIRECT = False # Always Set to False if using HAproxy
USE_X_FORWARDED_HOST = True
CSRF_FAILURE_VIEW = 'django.views.csrf.csrf_failure'
X_FRAME_OPTIONS = "SAMEORIGIN"

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7  # 1 week
SESSION_COOKIE_NAME = 'dlux_control_sessionid'
CSRF_COOKIE_NAME = 'dlux_control_csrftoken'
CSRF_COOKIE_SAMESITE = "Lax"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "csp",
    "health_check",
    "health_check.db",
    # DjangoLux generated apps start
    "fleet",
    # DjangoLux generated apps end
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "dlux_control_db"),
        "USER": os.getenv("POSTGRES_USER", "admin"),
        "PASSWORD": required_production_secret(
            "POSTGRES_PASSWORD", "POSTGRES_PASSWORD", "admin_pass"
        ),
        "HOST": os.getenv("POSTGRES_HOST", "db"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.getenv("REDIS_URL_DB", "redis://redis:6379/1"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 20,
            "CONNECTION_POOL_KWARGS": {"max_connections": 50},
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/2")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/3")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
FLEET_OPERATION_LOG_RETENTION_DAYS = int(os.getenv("FLEET_OPERATION_LOG_RETENTION_DAYS", "90"))

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False").lower() == "true"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = get_secret("EMAIL_HOST_PASSWORD", "EMAIL_HOST_PASSWORD") or ""
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "webmaster@localhost")

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [SELF],
        "script-src": [SELF, UNSAFE_INLINE, UNSAFE_EVAL],
        "style-src": [SELF, UNSAFE_INLINE],
        "img-src": [SELF, "data:", "blob:"],
        "font-src": [SELF, "data:"],
        "connect-src": [SELF, BASE_URL],
        "frame-ancestors": [SELF],
        "form-action": [SELF],
    }
}

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

dlux_settings(globals())
CELERY_BEAT_SCHEDULE["fleet-prune-operation-logs"] = {
    "task": "fleet.tasks.prune_operation_logs",
    "schedule": 86400.0,
}
CELERY_BEAT_SCHEDULE["fleet-expire-stale-operations"] = {
    "task": "fleet.tasks.expire_stale_operations",
    "schedule": 120.0,
}
