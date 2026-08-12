from django.db import migrations

PLAN_FEATURES = {
    "starter": [
        "Hosted checkout",
        "Signed webhooks",
        "Payment links",
        "API access",
    ],
    "standard": [
        "Hosted checkout",
        "Signed webhooks",
        "Payment links",
        "API access",
        "Delivery protection",
        "Request logs",
    ],
    "business": [
        "Hosted checkout",
        "Signed webhooks",
        "Payment links",
        "API access",
        "Delivery protection",
        "Request logs",
        "Refunds",
        "Team workspaces",
    ],
    "business-plus": [
        "Hosted checkout",
        "Signed webhooks",
        "Payment links",
        "API access",
        "Delivery protection",
        "Request logs",
        "Refunds",
        "Team workspaces",
        "Priority support",
        "KYB fast-track",
    ],
    "premium": [
        "Hosted checkout",
        "Signed webhooks",
        "Payment links",
        "API access",
        "Delivery protection",
        "Request logs",
        "Refunds",
        "Team workspaces",
        "Priority support",
        "KYB fast-track",
        "Dedicated account manager",
        "Custom settlement schedule",
    ],
    "enterprise": [
        "Hosted checkout",
        "Signed webhooks",
        "Payment links",
        "API access",
        "Delivery protection",
        "Request logs",
        "Refunds",
        "Team workspaces",
        "Priority support",
        "KYB fast-track",
        "Dedicated account manager",
        "Custom settlement schedule",
        "SLA guarantee",
        "Compliance reporting",
    ],
    "unlimited": [
        "Unlimited transactions",
        "All Enterprise features",
        "White-glove onboarding",
        "Custom integration support",
        "SLA guarantee",
        "Compliance reporting",
    ],
    "pay-as-you-go": [
        "Hosted checkout",
        "Signed webhooks",
        "API access",
        "No monthly fee",
    ],
}


def add_features(apps, schema_editor):
    PricingPlan = apps.get_model("billing", "PricingPlan")
    for code, features in PLAN_FEATURES.items():
        PricingPlan.objects.filter(code=code).update(features=features)


def remove_features(apps, schema_editor):
    PricingPlan = apps.get_model("billing", "PricingPlan")
    PricingPlan.objects.filter(code__in=PLAN_FEATURES.keys()).update(features=[])


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0013_extension_order"),
    ]

    operations = [
        migrations.RunPython(add_features, remove_features),
    ]
