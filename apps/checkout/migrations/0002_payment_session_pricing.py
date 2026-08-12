from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0002_pricing_configuration"),
        ("checkout", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentsession",
            name="fee_bearer",
            field=models.CharField(default="customer", max_length=12),
        ),
        migrations.AddField(
            model_name="paymentsession",
            name="pricing_plan_name",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
