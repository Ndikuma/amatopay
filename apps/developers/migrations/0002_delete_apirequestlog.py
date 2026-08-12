from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("developers", "0001_initial")]

    operations = [migrations.DeleteModel(name="ApiRequestLog")]
