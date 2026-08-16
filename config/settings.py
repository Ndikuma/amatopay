"""Django settings for AmatoPay.

Development defaults are convenient locally. Production values must be supplied
through the environment; see ``.env.example`` for the complete contract.
"""

from datetime import timedelta
from pathlib import Path
import sys
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse_lazy

from config.env import env, env_bool, env_int, env_list

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = env_bool("DEBUG", True)
SECRET_KEY = env("SECRET_KEY", "dev-only-change-me")
RELEASE_CODE_ENCRYPTION_KEYS = env_list("RELEASE_CODE_ENCRYPTION_KEYS")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
IS_MAKEMIGRATIONS = len(sys.argv) > 1 and sys.argv[1] == "makemigrations"

if not DEBUG and not IS_MAKEMIGRATIONS:
    if len(SECRET_KEY) < 50 or SECRET_KEY in {
        "dev-only-change-me",
        "replace-with-a-long-random-value",
    }:
        raise ImproperlyConfigured(
            "Production SECRET_KEY must be unique and at least 50 characters."
        )
    if not ALLOWED_HOSTS or ALLOWED_HOSTS == ["*"]:
        raise ImproperlyConfigured("Production ALLOWED_HOSTS must be explicit.")
    if not RELEASE_CODE_ENCRYPTION_KEYS:
        raise ImproperlyConfigured(
            "Production RELEASE_CODE_ENCRYPTION_KEYS must contain at least one Fernet key."
        )

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "django_filters",
    "apps.core",
    "apps.merchants",
    "apps.developers",
    "apps.billing",
    "apps.portal",
    "apps.checkout",
    "apps.payments",
    "apps.gateway.apps.GatewayConfig",
    "apps.fiduciary",
    "apps.deliveries",
    "apps.refunds",
    "apps.settlements",
    "apps.compliance",
    "apps.webhooks",
    "apps.security.apps.SecurityConfig",
]

UNFOLD = {
    "SITE_TITLE": "AmatoPay Operations",
    "SITE_HEADER": "AmatoPay",
    "SITE_SUBHEADER": "Payments control center",
    "SITE_SYMBOL": "account_balance_wallet",
    "SITE_URL": "/dashboard/",
    "SITE_VERSION": "1.0",
    "DASHBOARD_CALLBACK": "config.admin_dashboard.dashboard_callback",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "COLORS": {
        "primary": {
            "50": "#effcf9",
            "100": "#d7f8f1",
            "200": "#b2eee3",
            "300": "#7de0d1",
            "400": "#43cbbb",
            "500": "#11a89a",
            "600": "#0d897f",
            "700": "#106f69",
            "800": "#105954",
            "900": "#0e4946",
            "950": "#071f2b",
        }
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Overview",
                "items": [
                    {"title": "Operations dashboard", "icon": "space_dashboard", "link": reverse_lazy("admin:index")},
                ],
            },
            {
                "title": "Payments",
                "separator": True,
                "items": [
                    {"title": "Payments", "icon": "payments", "link": reverse_lazy("admin:payments_payment_changelist"), "badge": "config.admin_badges.pending_payments", "badge_variant": "warning"},
                    {"title": "Checkout sessions", "icon": "shopping_cart_checkout", "link": reverse_lazy("admin:checkout_paymentsession_changelist")},
                    {"title": "Protected funds", "icon": "shield_lock", "link": reverse_lazy("admin:fiduciary_fundhold_changelist"), "badge": "config.admin_badges.protected_funds", "badge_variant": "info"},
                    {"title": "Settlements", "icon": "account_balance", "link": reverse_lazy("admin:settlements_settlement_changelist"), "badge": "config.admin_badges.pending_settlements", "badge_variant": "warning"},
                    {"title": "Refunds", "icon": "currency_exchange", "link": reverse_lazy("admin:refunds_refund_changelist"), "badge": "config.admin_badges.pending_refunds", "badge_variant": "warning"},
                    {"title": "Protection claims", "icon": "verified_user", "link": reverse_lazy("admin:deliveries_protectionclaim_changelist"), "badge": "config.admin_badges.open_claims", "badge_variant": "danger"},
                ],
            },
            {
                "title": "Merchants",
                "separator": True,
                "items": [
                    {"title": "Merchant applications", "icon": "person_add", "link": reverse_lazy("admin:merchants_merchantapplication_changelist"), "badge": "config.admin_badges.merchant_applications", "badge_variant": "warning"},
                    {"title": "Merchant accounts", "icon": "storefront", "link": reverse_lazy("admin:merchants_merchant_changelist")},
                    {"title": "KYB reviews", "icon": "fact_check", "link": reverse_lazy("admin:merchants_merchantkyb_changelist"), "badge": "config.admin_badges.kyb_reviews", "badge_variant": "warning"},
                    {"title": "Documents", "icon": "folder_managed", "link": reverse_lazy("admin:merchants_merchantdocument_changelist")},
                    {"title": "Settlement accounts", "icon": "account_balance_wallet", "link": reverse_lazy("admin:merchants_merchantsettlementaccount_changelist")},
                ],
            },
            {
                "title": "Pricing",
                "separator": True,
                "items": [
                    {"title": "Pricing plans", "icon": "sell", "link": reverse_lazy("admin:billing_pricingplan_changelist")},
                    {"title": "Plan assignments", "icon": "assignment_ind", "link": reverse_lazy("admin:billing_merchantplanassignment_changelist")},
                    {"title": "Fee snapshots", "icon": "request_quote", "link": reverse_lazy("admin:payments_transactionfee_changelist")},
                ],
            },
            {
                "title": "Gateway",
                "separator": True,
                "items": [
                    {"title": "Configuration", "icon": "hub", "link": reverse_lazy("admin:cecf_gatewayconfig_changelist"), "badge": "config.admin_badges.gateway_state", "badge_variant": "success"},
                    {"title": "Alias verification", "icon": "person_search", "link": reverse_lazy("admin:cecf_aliasverification_changelist")},
                    {"title": "RTP collection", "icon": "call_received", "link": reverse_lazy("admin:cecf_rtprequest_changelist"), "badge": "config.admin_badges.pending_rtp", "badge_variant": "warning"},
                    {"title": "P2P settlement", "icon": "call_made", "link": reverse_lazy("admin:cecf_p2prequest_changelist"), "badge": "config.admin_badges.pending_p2p", "badge_variant": "warning"},
                    {"title": "Transaction monitoring", "icon": "monitor_heart", "link": reverse_lazy("admin:cecf_gatewaytransactionpoll_changelist")},
                ],
            },
            {
                "title": "Compliance & platform",
                "separator": True,
                "badge": "config.admin_badges.compliance_attention",
                "badge_variant": "danger",
                "items": [
                    {"title": "Suspicious activity", "icon": "policy", "link": reverse_lazy("admin:compliance_suspicioustransaction_changelist"), "badge": "config.admin_badges.compliance_attention", "badge_variant": "danger"},
                    {"title": "Regulatory reports", "icon": "assured_workload", "link": reverse_lazy("admin:compliance_regulatoryreport_changelist")},
                    {"title": "Webhook deliveries", "icon": "webhook", "link": reverse_lazy("admin:webhooks_webhookdelivery_changelist"), "badge": "config.admin_badges.webhook_failures", "badge_variant": "danger"},
                    {"title": "Webhook attempts", "icon": "history", "link": reverse_lazy("admin:webhooks_webhookattempt_changelist")},
                    {"title": "Audit trail", "icon": "history", "link": reverse_lazy("admin:core_auditevent_changelist")},
                    {"title": "Security center", "icon": "security", "link": reverse_lazy("security-dashboard"), "badge": "config.admin_badges.security_alerts", "badge_variant": "danger"},
                ],
            },
        ],
    },
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
TESTING = "test" in sys.argv
if not TESTING:
    MIDDLEWARE[6:6] = [
        "apps.security.middleware.SecurityTrackingMiddleware",
        "apps.security.middleware.CircuitBreakerMiddleware",
        "apps.security.middleware.RateLimitMiddleware",
        "apps.security.middleware.AuthenticatedRateLimitMiddleware",
        "apps.security.middleware.RequestThrottlingMiddleware",
    ]

ROOT_URLCONF = "config.urls"
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
                "apps.portal.context_processors.merchant_access",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
DATABASES["security"] = {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": env("SECURITY_DB_NAME", BASE_DIR / "security.sqlite3"),
}
DATABASE_ROUTERS = ["apps.security.db_router.SecurityDatabaseRouter"]
SECURITY_ENDPOINTS_FILE = BASE_DIR / "apps" / "security" / "endpoints.yaml"
if env("POSTGRES_DB"):
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER", ""),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": env_int("POSTGRES_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "sslmode": env("POSTGRES_SSLMODE", "prefer" if DEBUG else "require")
        },
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Bujumbura"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.developers.authentication.MerchantApiKeyAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    "EXCEPTION_HANDLER": "rest_framework.views.exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
}

DOMESTIC_HOLD_BUSINESS_DAYS = env_int("DOMESTIC_HOLD_BUSINESS_DAYS", 4)
INTERNATIONAL_HOLD_CALENDAR_DAYS = env_int("INTERNATIONAL_HOLD_CALENDAR_DAYS", 14)

LOGIN_URL = "/account/sign-in/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "AmatoPay <no-reply@amatopay.bi>")
SECURE_REFERRER_POLICY = "same-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
FILE_UPLOAD_MAX_MEMORY_SIZE = env_int("FILE_UPLOAD_MAX_MEMORY_SIZE", 5 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = env_int("DATA_UPLOAD_MAX_MEMORY_SIZE", 6 * 1024 * 1024)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": (
                '{{"time":"{asctime}","level":"{levelname}",'
                '"logger":"{name}","message":"{message}"}}'
            ),
            "style": "{",
        }
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# ============================================================================
# AmatoPay API - drf-spectacular settings
# ============================================================================

SPECTACULAR_SETTINGS = {
    "TITLE": "AmatoPay API",
    "VERSION": "2.0.0",

    "DESCRIPTION": """
# AmatoPay Payment Gateway API

AmatoPay is a secure and reliable payment processing solution for merchants
in Burundi.

## Overview

AmatoPay enables merchants to:

- Accept mobile money payments
- Verify payer identities
- Track payment status in real-time
- Manage checkout sessions
- Receive webhook notifications

## Authentication

Most API endpoints require API key authentication using
`MerchantApiKeyAuthentication`.

**Authorization Header:**

`Authorization: Api-Key YOUR_API_KEY`

## Payment Flow

1. **Verify Payer Alias** - Validate that the payer exists and is payable.
2. **Create Checkout Session** - Initiate a payment session.
3. **Customer Payment** - Customer completes payment through hosted checkout.
4. **Check Status** - Check the payment status until it reaches a final state.
5. **Return to Merchant** - Customer is redirected to the configured `return_url`.

## Payment Statuses

| Status | Description | Terminal |
|---|---|---|
| pending | Payment is being processed | No |
| paid | Payment completed successfully | Yes |
| funds_held | Funds are on hold | Yes |
| delivery_pending | Awaiting delivery confirmation | Yes |
| settled | Payment settled | Yes |
| failed | Payment failed | Yes |
| rejected | Payment rejected | Yes |
| cancelled | Payment cancelled | Yes |
| expired | Payment expired | Yes |
| refunded | Payment refunded | Yes |

## Error Handling

Standard HTTP status codes are used:

- `200` - Successful request
- `400` - Validation error
- `403` - Permission denied
- `404` - Resource not found
- `500` - Internal server error

## Rate Limiting

API requests are rate-limited to prevent abuse.
Contact support if you require a higher limit.

""",

    # ------------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------------
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "SCHEMA_PATH_PREFIX_TRIM": False,
    "COMPONENT_SPLIT_REQUEST": True,

    # ------------------------------------------------------------------------
    # Swagger / Redoc
    # ------------------------------------------------------------------------
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",

    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
        "filter": True,
        "displayRequestDuration": True,
        "tryItOutEnabled": True,
        "docExpansion": "list",
        "tagsSorter": "alpha",
        "operationsSorter": "alpha",
    },

    "REDOC_SETTINGS": {
        "lazyRendering": True,
        "hideLoading": False,
        "disableSearch": False,
        "scrollYOffset": 10,
        "theme": {
            "colors": {
                "primary": {"main": "#1A237E"},
                "success": {"main": "#27AE60"},
                "warning": {"main": "#F39C12"},
                "error": {"main": "#E74C3C"},
                "info": {"main": "#3498DB"},
                "text": {
                    "primary": "#1A237E",
                    "secondary": "#546E7A",
                },
                "border": {"main": "#B0BEC5"},
            },
            "typography": {
                "fontSize": "14px",
                "lineHeight": "1.5",
                "fontFamily": (
                    "-apple-system, BlinkMacSystemFont, "
                    "'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
                ),
            },
        },
    },

    # ------------------------------------------------------------------------
    # API Tags
    # ------------------------------------------------------------------------
    "TAGS": [
    
        {
            "name": "Checkout",
            "description": "Manage checkout sessions and payment status tracking",
        },
        {
            "name": "Payments",
            "description": "Payment processing and management",
        },
    ],
    # ------------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------------
    "SECURITY": [
        {
            "ApiKeyAuth": [],
        },
    ],

    "SECURITY_DEFINITIONS": {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "API key authentication. Format: `Api-Key YOUR_API_KEY`",
        },
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT authentication for internal services",
        },
    },

    # ------------------------------------------------------------------------
    # Schema behavior
    # ------------------------------------------------------------------------
    "SCHEMA_COERCE_PATH_PK": True,

    "SCHEMA_COERCE_METHOD_NAMES": {
        "retrieve": "read",
        "destroy": "delete",
        "update": "update",
        "partial_update": "partial_update",
        "list": "list",
        "create": "create",
    },

    # ------------------------------------------------------------------------
    # API serving / ordering
    # ------------------------------------------------------------------------
    "SERVE_PERMISSIONS": [],
    "SERVE_AUTHENTICATION": [],

    "SORT_OPERATIONS": True,
    "SORT_OPERATION_PARAMETERS": True,
    "SORT_OPERATION_PARAMETER_GROUPS": True,
    "SORT_TAGS": True,

    "OPERATION_ID_SOURCE": "method",
}