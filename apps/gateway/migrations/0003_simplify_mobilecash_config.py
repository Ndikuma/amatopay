from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("cecf", "0002_gatewayconfig")]
    operations = [
        migrations.RemoveField(model_name="gatewayconfig", name="client_id"),
        migrations.RemoveField(model_name="gatewayconfig", name="client_secret"),
        migrations.RemoveField(model_name="gatewayconfig", name="mode"),
    ]
