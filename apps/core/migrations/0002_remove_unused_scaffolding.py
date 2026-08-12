from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS risk_riskassessment",
                "DROP TABLE IF EXISTS risk_screeningresult",
                "DROP TABLE IF EXISTS risk_riskrule",
                "DROP TABLE IF EXISTS risk_transactionlimit",
                "DROP TABLE IF EXISTS reconciliation_reconciliationitem",
                "DROP TABLE IF EXISTS reconciliation_reconciliationrun",
            ],
            reverse_sql=migrations.RunSQL.noop,
        )
    ]
