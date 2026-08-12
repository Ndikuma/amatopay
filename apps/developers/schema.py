from drf_spectacular.extensions import OpenApiAuthenticationExtension


class MerchantApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.developers.authentication.MerchantApiKeyAuthentication"
    name = ["AmatoPayApiKey", "AmatoPayBearerKey"]

    def get_security_definition(self, auto_schema):
        return [
            {
                "type": "apiKey",
                "in": "header",
                "name": "X-Api-Key",
                "description": "AmatoPay merchant secret key (sk_…).",
            },
            {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "AmatoPay API key",
                "description": "The same merchant secret key passed as a Bearer token.",
            },
        ]
