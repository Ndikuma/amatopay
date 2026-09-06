"""Merchant onboarding / activation state.

A merchant may operate with AmatoPay only once every activation check passes:
the profile is complete, KYB documents are submitted and verified, KYB is
approved, a primary settlement account is verified, and the account is active.
"""

from django.core.exceptions import ObjectDoesNotExist

from .models import Merchant, MerchantKYB

ACTIVATION_LABELS = {
    "business_identity": "Legal name, registration number and tax ID on file",
    "contact_details": "Business email, phone and address on file",
    "source_of_funds": "Source of funds declared",
    "kyb_documents_submitted": "KYB documents uploaded",
    "kyb_documents_verified": "KYB documents verified by AmatoPay",
    "kyb_approved": "KYB review approved",
    "settlement_account_verified": "Primary settlement account verified",
    "account_active": "Merchant account activated",
}


def activation_status(merchant):
    try:
        kyb = merchant.kyb
    except ObjectDoesNotExist:
        kyb = None

    documents = merchant.kyb_documents.all()
    accounts = merchant.settlement_accounts.all()

    checks = {
        "business_identity": bool(
            merchant.legal_name and merchant.registration_number and merchant.tax_id
        ),
        "contact_details": bool(
            merchant.email and merchant.phone and merchant.address
        ),
        "source_of_funds": bool(kyb and kyb.source_of_funds),
        "kyb_documents_submitted": documents.exists(),
        "kyb_documents_verified": documents.filter(verified=True).exists(),
        "kyb_approved": bool(
            kyb
            and kyb.verified
            and kyb.decision == MerchantKYB.Decision.APPROVED
        ),
        "settlement_account_verified": accounts.filter(
            verification_status="verified",
            is_primary=True,
            is_active=True,
            currency=merchant.default_currency,
        ).exists(),
        "account_active": merchant.status == Merchant.Status.ACTIVE,
    }

    completed = sum(1 for ok in checks.values() if ok)
    total = len(checks)
    return {
        "checks": checks,
        "labels": ACTIVATION_LABELS,
        "readiness": round(completed / total * 100),
        "completed": completed,
        "total": total,
        "can_operate": completed == total,
        "pending": [name for name, ok in checks.items() if not ok],
    }
