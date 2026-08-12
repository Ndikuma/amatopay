from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='RequestLog',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp',    models.DateTimeField(auto_now_add=True, db_index=True)),
                ('ip_address',   models.GenericIPAddressField(db_index=True)),
                ('method',       models.CharField(max_length=10)),
                ('path',         models.CharField(max_length=2000)),
                ('query_string', models.CharField(blank=True, max_length=2000)),
                ('status_code',  models.SmallIntegerField(db_index=True)),
                ('response_ms',  models.PositiveIntegerField(default=0)),
                ('user_agent',   models.CharField(blank=True, max_length=500)),
                ('referer',      models.CharField(blank=True, max_length=500)),
                ('is_api',       models.BooleanField(default=False, db_index=True)),
                ('merchant_id',  models.CharField(blank=True, max_length=100)),
                ('country_code', models.CharField(blank=True, max_length=2)),
            ],
            options={'db_table': 'sec_request_log', 'ordering': ['-timestamp']},
        ),
        migrations.AddIndex(
            model_name='requestlog',
            index=models.Index(fields=['ip_address', 'timestamp'], name='sec_req_ip_ts_idx'),
        ),
        migrations.AddIndex(
            model_name='requestlog',
            index=models.Index(fields=['status_code', 'timestamp'], name='sec_req_sc_ts_idx'),
        ),
        migrations.CreateModel(
            name='SecurityAlert',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp',   models.DateTimeField(auto_now_add=True, db_index=True)),
                ('severity',    models.CharField(
                    choices=[('info','Info'),('low','Low'),('medium','Medium'),('high','High'),('critical','Critical')],
                    db_index=True, max_length=10,
                )),
                ('alert_type',  models.CharField(
                    choices=[
                        ('brute_force','Brute Force'),('rate_limit','Rate Limit'),
                        ('scanning','Scanning'),('injection','Injection Attempt'),
                        ('path_traversal','Path Traversal'),('suspicious_ua','Suspicious User-Agent'),
                        ('blocked_attempt','Blocked IP Attempt'),('admin_probe','Admin Probe'),
                    ],
                    db_index=True, max_length=30,
                )),
                ('ip_address',  models.GenericIPAddressField(db_index=True)),
                ('path',        models.CharField(max_length=2000)),
                ('detail',      models.TextField()),
                ('resolved',    models.BooleanField(default=False, db_index=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('resolved_by', models.CharField(blank=True, max_length=100)),
                ('request_log', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='alerts',
                    to='security.requestlog',
                )),
            ],
            options={'db_table': 'sec_alert', 'ordering': ['-timestamp']},
        ),
        migrations.AddIndex(
            model_name='securityalert',
            index=models.Index(fields=['resolved', 'severity'], name='sec_alert_res_sev_idx'),
        ),
        migrations.AddIndex(
            model_name='securityalert',
            index=models.Index(fields=['ip_address', 'timestamp'], name='sec_alert_ip_ts_idx'),
        ),
        migrations.CreateModel(
            name='BlockedIP',
            fields=[
                ('id',         models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip_address', models.GenericIPAddressField(db_index=True, unique=True)),
                ('reason',     models.CharField(max_length=500)),
                ('blocked_at', models.DateTimeField(auto_now_add=True)),
                ('blocked_by', models.CharField(default='system', max_length=100)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('is_active',  models.BooleanField(default=True, db_index=True)),
            ],
            options={'db_table': 'sec_blocked_ip', 'ordering': ['-blocked_at']},
        ),
    ]
