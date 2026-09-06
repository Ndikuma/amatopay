from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.checkout.models import PaymentSession
from apps.compliance import reports
from apps.compliance.exports import to_csv, to_pdf
from apps.compliance.models import (
    DataRetentionRecord,
    RegulatoryReport,
    SuspiciousTransaction,
)
from apps.merchants.models import Merchant
from apps.payments.models import Payment

_ORDER_SEQ = 0


def _backdate(instance, when):
    """Force ``created_at`` past the ``auto_now_add`` guard for range tests."""
    type(instance).objects.filter(pk=instance.pk).update(created_at=when)


def _make_payment(merchant, amount, fee_amount=Decimal("0.00"), status=None):
    global _ORDER_SEQ
    _ORDER_SEQ += 1
    session = PaymentSession.objects.create(
        merchant=merchant,
        order_number=f"RPT-ORDER-{_ORDER_SEQ}",
        description="Compliance report test",
        amount=amount,
        fee_amount=fee_amount,
        fee_source="PAY_AS_YOU_GO",
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return Payment.objects.create(
        merchant=merchant,
        session=session,
        amount=amount,
        fee_amount=fee_amount,
        fee_source="PAY_AS_YOU_GO",
        status=status or Payment.Status.CREATED,
    )


class ReportRegistryTests(TestCase):
    def test_every_report_is_registered_with_metadata(self):
        self.assertIn("transactions", reports.REPORTS)
        for key, meta in reports.REPORTS.items():
            self.assertEqual(meta["key"], key)
            self.assertTrue(meta["label"])
            self.assertTrue(callable(meta["fn"]))

    def test_report_choices_are_sorted_key_label_pairs(self):
        choices = reports.report_choices()
        self.assertEqual(choices, sorted(choices))
        self.assertIn(("transactions", "Transactions"), choices)

    def test_generate_rejects_unknown_report(self):
        with self.assertRaises(KeyError):
            reports.generate("does-not-exist", date(2026, 1, 1), date(2026, 1, 31))


class TransactionsReportTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-RPT-1",
            legal_name="Report Merchant",
            display_name="Report Merchant",
            status=Merchant.Status.ACTIVE,
        )
        self.inside = _make_payment(
            self.merchant, Decimal("100000.00"), Decimal("5000.00"),
            status=Payment.Status.SETTLED,
        )
        _backdate(self.inside, timezone.make_aware(timezone.datetime(2026, 6, 15, 12, 0)))
        self.outside = _make_payment(
            self.merchant, Decimal("42000.00"), Decimal("2100.00"),
            status=Payment.Status.CREATED,
        )
        _backdate(self.outside, timezone.make_aware(timezone.datetime(2026, 7, 2, 9, 0)))

    def test_only_rows_in_the_period_are_returned(self):
        data = reports.generate("transactions", date(2026, 6, 1), date(2026, 6, 30))
        self.assertEqual(len(data.rows), 1)
        self.assertEqual(data.rows[0][0], self.inside.reference)
        self.assertEqual(data.summary["count"], 1)
        self.assertEqual(data.summary["settled_count"], 1)
        self.assertEqual(data.summary["gross_total"], "100000.00")
        self.assertEqual(data.summary["fee_total"], "5000.00")

    def test_period_boundaries_are_inclusive(self):
        data = reports.generate("transactions", date(2026, 6, 15), date(2026, 6, 15))
        self.assertEqual(len(data.rows), 1)

    def test_empty_period_yields_zeroed_summary(self):
        data = reports.generate("transactions", date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(data.rows, [])
        self.assertEqual(data.summary["count"], 0)
        self.assertEqual(data.summary["gross_total"], "0.00")


class SuspiciousActivityReportTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-RPT-2",
            legal_name="STR Merchant",
            display_name="STR Merchant",
            status=Merchant.Status.ACTIVE,
        )
        payment = _make_payment(self.merchant, Decimal("9000000.00"))
        self.str_report = SuspiciousTransaction.objects.create(
            payment=payment,
            reason="Structuring across multiple aliases",
            indicators=["structuring", "velocity"],
            status="open",
            reported_to_brb=True,
        )
        _backdate(
            self.str_report,
            timezone.make_aware(timezone.datetime(2026, 6, 10, 8, 0)),
        )

    def test_report_summarises_filing_status(self):
        data = reports.generate("suspicious_activity", date(2026, 6, 1), date(2026, 6, 30))
        self.assertEqual(data.summary["count"], 1)
        self.assertEqual(data.summary["open_count"], 1)
        self.assertEqual(data.summary["reported_brb_count"], 1)
        self.assertEqual(data.summary["reported_cnrf_count"], 0)
        self.assertIn("structuring, velocity", data.rows[0])


class DataRetentionReportTests(TestCase):
    def test_counts_archived_records(self):
        kept = DataRetentionRecord.objects.create(
            object_type="payment",
            object_id="p-1",
            retain_until=date(2031, 1, 1),
            legal_basis="BRB Circular 008/SP/2026",
        )
        archived = DataRetentionRecord.objects.create(
            object_type="payment",
            object_id="p-2",
            retain_until=date(2026, 1, 1),
            legal_basis="BRB Circular 008/SP/2026",
            archived=True,
        )
        for rec in (kept, archived):
            _backdate(rec, timezone.make_aware(timezone.datetime(2026, 6, 5, 0, 0)))
        data = reports.generate("data_retention", date(2026, 6, 1), date(2026, 6, 30))
        self.assertEqual(data.summary["count"], 2)
        self.assertEqual(data.summary["archived_count"], 1)


class ExportRendererTests(TestCase):
    data = reports.ReportData(
        columns=["Reference", "Amount"],
        rows=[["AMP-1", "100000.00"], ["AMP-2", "5000.00"]],
        summary={"count": 2, "gross_total": "105000.00"},
    )
    meta = {
        "title": "Transactions test",
        "type_label": "Transactions",
        "period_start": date(2026, 6, 1),
        "period_end": date(2026, 6, 30),
        "generated_at": "2026-07-01 09:00",
        "generated_by": "auditor",
        "slug": "transactions-test",
    }

    def test_csv_contains_meta_summary_and_rows(self):
        body = to_csv(self.data, self.meta).decode("utf-8-sig")
        self.assertIn("compliance report", body)
        self.assertIn("Transactions test", body)
        self.assertIn("summary:gross_total,105000.00", body)
        self.assertIn("Reference,Amount", body)
        self.assertIn("AMP-1,100000.00", body)

    def test_pdf_is_a_pdf_document(self):
        blob = to_pdf(self.data, self.meta)
        self.assertTrue(blob.startswith(b"%PDF"))
        self.assertGreater(len(blob), 800)

    def test_pdf_handles_an_empty_report(self):
        empty = reports.ReportData(columns=["Reference", "Amount"], rows=[], summary={})
        blob = to_pdf(empty, self.meta)
        self.assertTrue(blob.startswith(b"%PDF"))


class RegulatoryReportAdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="compliance-officer", password="safe-test-password-2026"
        )
        self.client.force_login(self.admin)
        self.merchant = Merchant.objects.create(
            merchant_code="AMP-RPT-3",
            legal_name="Admin Merchant",
            display_name="Admin Merchant",
            status=Merchant.Status.ACTIVE,
        )
        payment = _make_payment(
            self.merchant, Decimal("250000.00"), Decimal("12500.00"),
            status=Payment.Status.SETTLED,
        )
        _backdate(payment, timezone.make_aware(timezone.datetime(2026, 6, 20, 10, 0)))

    def _add(self, **overrides):
        payload = {
            "report_type": "transactions",
            "period_start": "2026-06-01",
            "period_end": "2026-06-30",
            "notes": "Monthly BRB filing",
        }
        payload.update(overrides)
        return self.client.post(
            reverse("admin:compliance_regulatoryreport_add"), payload, follow=True
        )

    def test_creating_a_report_freezes_a_snapshot(self):
        response = self._add()
        self.assertEqual(response.status_code, 200)
        report = RegulatoryReport.objects.get()
        self.assertEqual(report.status, RegulatoryReport.Status.GENERATED)
        self.assertEqual(report.row_count, 1)
        self.assertEqual(report.generated_by, self.admin)
        self.assertEqual(report.payload["columns"][0], "Reference")
        self.assertEqual(len(report.payload["rows"]), 1)
        self.assertIn("generated_at", report.payload)
        self.assertTrue(report.title.startswith("Transactions"))

    def test_end_date_before_start_date_is_rejected(self):
        self._add(period_start="2026-06-30", period_end="2026-06-01")
        self.assertFalse(RegulatoryReport.objects.exists())

    def test_snapshot_is_not_regenerated_on_edit(self):
        self._add()
        report = RegulatoryReport.objects.get()
        original = report.payload
        _make_payment(self.merchant, Decimal("1.00"), status=Payment.Status.SETTLED)
        self.client.post(
            reverse("admin:compliance_regulatoryreport_change", args=[report.pk]),
            {
                "status": RegulatoryReport.Status.REVIEWED,
                "notes": "Reviewed and ready",
            },
            follow=True,
        )
        report.refresh_from_db()
        self.assertEqual(report.payload, original)
        self.assertEqual(report.status, RegulatoryReport.Status.REVIEWED)

    def test_download_view_serves_csv_and_pdf_from_the_snapshot(self):
        self._add()
        report = RegulatoryReport.objects.get()
        url = reverse(
            "admin:compliance_regulatoryreport_download", args=[report.pk]
        )

        csv_response = self.client.get(url, {"format": "csv"})
        self.assertEqual(csv_response["Content-Type"], "text/csv")
        self.assertIn("attachment", csv_response["Content-Disposition"])
        self.assertIn(b"Reference", csv_response.content)

        pdf_response = self.client.get(url, {"format": "pdf"})
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")
        self.assertTrue(pdf_response.content.startswith(b"%PDF"))
