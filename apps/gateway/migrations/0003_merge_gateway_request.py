"""Merge RTPRequest/P2PRequest into GatewayRequest and the two callback models
into GatewayCallback.

The RTP tables are renamed in place (no data copy); the P2P rows are copied into
the unified tables keeping their original primary keys, then the P2P models are
dropped.
"""

import django.db.models.deletion
from django.db import migrations, models


def copy_p2p_rows(apps, schema_editor):
    GatewayRequest = apps.get_model("cecf", "GatewayRequest")
    GatewayCallback = apps.get_model("cecf", "GatewayCallback")
    P2PRequest = apps.get_model("cecf", "P2PRequest")
    P2PCallback = apps.get_model("cecf", "P2PCallback")

    for p2p in P2PRequest.objects.all().iterator():
        GatewayRequest.objects.create(
            id=p2p.id,
            rail="P2P",
            request_id=p2p.request_id,
            settlement_id=p2p.settlement_id,
            provider_reference=p2p.provider_reference,
            status=p2p.status,
            last_callback_at=p2p.last_callback_at,
            raw_request=p2p.raw_request,
            raw_response=p2p.raw_response,
            last_polled_at=p2p.last_polled_at,
            next_poll_at=p2p.next_poll_at,
            poll_attempts=p2p.poll_attempts,
            consecutive_poll_failures=p2p.consecutive_poll_failures,
            last_poll_error=p2p.last_poll_error,
        )
        GatewayRequest.objects.filter(pk=p2p.id).update(
            created_at=p2p.created_at, updated_at=p2p.updated_at
        )

    for cb in P2PCallback.objects.all().iterator():
        GatewayCallback.objects.create(
            id=cb.id,
            event_id=cb.event_id,
            request_id=cb.p2p_id,
            status=cb.status,
            reason_code=cb.reason_code,
            payload=cb.payload,
        )
        GatewayCallback.objects.filter(pk=cb.id).update(
            created_at=cb.created_at, updated_at=cb.updated_at
        )


def restore_p2p_rows(apps, schema_editor):
    GatewayRequest = apps.get_model("cecf", "GatewayRequest")
    GatewayCallback = apps.get_model("cecf", "GatewayCallback")
    P2PRequest = apps.get_model("cecf", "P2PRequest")
    P2PCallback = apps.get_model("cecf", "P2PCallback")

    for row in GatewayRequest.objects.filter(rail="P2P").iterator():
        P2PRequest.objects.create(
            id=row.id,
            request_id=row.request_id,
            settlement_id=row.settlement_id,
            provider_reference=row.provider_reference,
            status=row.status,
            last_callback_at=row.last_callback_at,
            raw_request=row.raw_request,
            raw_response=row.raw_response,
            last_polled_at=row.last_polled_at,
            next_poll_at=row.next_poll_at,
            poll_attempts=row.poll_attempts,
            consecutive_poll_failures=row.consecutive_poll_failures,
            last_poll_error=row.last_poll_error,
        )
        P2PRequest.objects.filter(pk=row.id).update(
            created_at=row.created_at, updated_at=row.updated_at
        )

    for cb in GatewayCallback.objects.filter(request__rail="P2P").iterator():
        P2PCallback.objects.create(
            id=cb.id,
            event_id=cb.event_id,
            p2p_id=cb.request_id,
            status=cb.status,
            reason_code=cb.reason_code,
            payload=cb.payload,
        )
        P2PCallback.objects.filter(pk=cb.id).update(
            created_at=cb.created_at, updated_at=cb.updated_at
        )

    GatewayCallback.objects.filter(request__rail="P2P").delete()
    GatewayRequest.objects.filter(rail="P2P").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cecf", "0002_remove_rtprequest_extension_order"),
        ("settlements", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel("RTPRequest", "GatewayRequest"),
        migrations.RenameModel("RTPCallback", "GatewayCallback"),
        migrations.RenameField("GatewayCallback", "rtp", "request"),
        migrations.AddField(
            model_name="gatewayrequest",
            name="rail",
            field=models.CharField(
                choices=[("RTP", "RTP collection"), ("P2P", "P2P payout")],
                db_index=True,
                default="RTP",
                max_length=3,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="gatewayrequest",
            name="settlement",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="settlements.settlement",
            ),
        ),
        migrations.AlterField(
            model_name="gatewayrequest",
            name="release_code_ciphertext",
            field=models.TextField(
                blank=True, editable=False, help_text="RTP collections only."
            ),
        ),
        migrations.AlterField(
            model_name="gatewayrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("awaiting_approval", "Awaiting payer approval"),
                    ("completed", "Completed"),
                    ("rejected", "Rejected"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                    ("expired", "Expired"),
                ],
                default="pending",
                max_length=30,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="gatewayrequest",
            name="uq_rtp_gateway_trx_ref",
        ),
        migrations.AddConstraint(
            model_name="gatewayrequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(("provider_reference", ""), _negated=True),
                fields=("provider_reference",),
                name="uq_gateway_request_trx_ref",
            ),
        ),
        migrations.AddIndex(
            model_name="gatewayrequest",
            index=models.Index(
                fields=["rail", "status"], name="idx_gwreq_rail_status"
            ),
        ),
        migrations.RunPython(copy_p2p_rows, restore_p2p_rows),
        migrations.DeleteModel("P2PCallback"),
        migrations.DeleteModel("P2PRequest"),
        migrations.AlterField(
            model_name="gatewayrequest",
            name="settlement",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="p2p",
                to="settlements.settlement",
            ),
        ),
    ]
