from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cecf", "0006_p2prequest_consecutive_poll_failures_and_more")]

    operations = [
        migrations.AddField(
            model_name="rtprequest",
            name="release_code_ciphertext",
            field=models.TextField(blank=True, editable=False),
        ),
    ]
