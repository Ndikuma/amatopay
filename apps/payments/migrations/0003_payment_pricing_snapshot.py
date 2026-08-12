from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("checkout", "0002_payment_session_pricing"),
        ("payments", "0002_payment_release_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="fee_bearer",
            field=models.CharField(default="customer", max_length=12),
        ),
        migrations.AddField(
            model_name="payment",
            name="pricing_plan_name",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
