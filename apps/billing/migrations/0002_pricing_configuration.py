from decimal import Decimal

from django.db import migrations, models


def create_default_plan(apps, schema_editor):
    PricingPlan = apps.get_model("billing", "PricingPlan")
    PricingPlan.objects.create(
        name="AmatoPay Standard",
        active=True,
        is_default=True,
        fee_bearer="customer",
        fixed_fee=Decimal("0.00"),
        percentage_fee=Decimal("2.5000"),
        tax_rate=Decimal("0.0000"),
        min_fee=Decimal("100.00"),
        max_fee=Decimal("10000.00"),
        currency="BIF",
    )


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="pricingplan",
            name="fee_bearer",
            field=models.CharField(
                choices=[
                    ("customer", "Customer pays fee"),
                    ("merchant", "Merchant pays fee"),
                ],
                default="customer",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="pricingplan",
            name="is_default",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="pricingplan",
            name="tax_rate",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=7),
        ),
        migrations.AddConstraint(
            model_name="pricingplan",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_default", True)),
                fields=("is_default",),
                name="uq_default_pricing_plan",
            ),
        ),
        migrations.RunPython(create_default_plan, migrations.RunPython.noop),
    ]
