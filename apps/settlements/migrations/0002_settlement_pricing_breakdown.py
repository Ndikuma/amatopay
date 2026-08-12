from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0003_payment_pricing_snapshot"),
        ("settlements", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="settlement",
            name="collected_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=20),
        ),
        migrations.AddField(
            model_name="settlement",
            name="fee_bearer",
            field=models.CharField(default="customer", max_length=12),
        ),
        migrations.AddField(
            model_name="settlement",
            name="platform_fee_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=20),
        ),
        migrations.AddField(
            model_name="settlement",
            name="platform_fee_tax_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=20),
        ),
    ]
