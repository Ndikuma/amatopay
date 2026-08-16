"""
BurundiPay API Views Module

This module contains the view functions for the BurundiPay payment processing system.
It handles merchant alias verification and checkout session status retrieval.

Endpoints:
- merchant_alias_verify: Verify a payer's mobile alias
- checkout_status: Get the status of a hosted checkout payment session
"""

import hmac
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError
from rest_framework import serializers
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.checkout.models import PaymentSession
from apps.developers.authentication import MerchantApiKeyAuthentication
from apps.developers.permissions import HasMerchantApiKey
from apps.gateway.services import AliasNotPayableError, verify_merchant_payer_alias
from .alias_serializers import (
    MerchantAliasVerificationResultSerializer,
    MerchantAliasVerificationSerializer,
)


@extend_schema(
    summary="Verify a payer MOBILE alias",
    description="Look up an active MOBILE payer alias and return its registered customer name.",
    parameters=[OpenApiParameter("payer_alias", str, OpenApiParameter.QUERY, required=True)],
    request=None,
    responses={200: MerchantAliasVerificationResultSerializer},
)
@api_view(["GET"])
@authentication_classes([MerchantApiKeyAuthentication])
@permission_classes([HasMerchantApiKey])
def merchant_alias_verify(request):
    """
    Verify a payer's mobile alias for the authenticated merchant.
    
    This endpoint checks if a given mobile alias is valid and payable by the merchant.
    It returns the registered customer information if the alias is found and active.
    
    Args:
        request (Request): The HTTP request object containing query parameters
        
    Returns:
        Response: JSON response with alias verification details
        
    Raises:
        ValidationError: If the payer alias is not payable
        PermissionDenied: If merchant doesn't have permission to verify aliases
        
    Example Response:
        {
            "alias_type": "MOBILE",
            "payer_alias": "+25712345678",
            "found": true,
            "status": "active",
            "customer_full_name": "John Doe",
            "currency": "BIF"
        }
    """
    # Validate the query parameters using the serializer
    serializer = MerchantAliasVerificationSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    
    try:
        # Verify the payer alias for the merchant
        verification = verify_merchant_payer_alias(
            merchant=request.merchant,
            payer_alias=serializer.validated_data["payer_alias"],
        )
    except AliasNotPayableError as exc:
        # Raise validation error if alias is not payable
        raise ValidationError({"payer_alias": str(exc)}) from exc
    
    # Return the verification result
    return Response(
        {
            "alias_type": "MOBILE",
            "payer_alias": verification.alias_value,
            "found": verification.found,
            "status": verification.status,
            "customer_full_name": verification.display_name,
            "currency": verification.currency,
        }
    )


def _session(session_id, client_secret):
    """
    Internal helper function to validate and retrieve a payment session.
    
    This function performs several validation checks:
    1. Fetches the session from the database with merchant relation
    2. Verifies the client secret using HMAC comparison
    3. Checks if the session has expired
    4. Automatically updates expired sessions
    5. Checks if the session was cancelled
    
    Args:
        session_id (str): The UUID of the payment session
        client_secret (str): The client secret associated with the session
        
    Returns:
        PaymentSession: The validated payment session object
        
    Raises:
        PermissionDenied: If the client secret is invalid
        ValidationError: If the session is expired or cancelled
        ObjectDoesNotExist: If the session is not found
    """
    # Fetch the session with merchant relation
    s = get_object_or_404(
        PaymentSession.objects.select_related("merchant"), 
        session_id=session_id
    )
    
    # Verify client secret using HMAC comparison (timing attack safe)
    if not hmac.compare_digest(s.client_secret, client_secret):
        raise PermissionDenied("Invalid checkout client secret.")
    
    # Check if session has expired
    if s.expires_at <= timezone.now():
        # Auto-update expired sessions to EXPIRED status
        if s.status not in {
            PaymentSession.Status.COMPLETED,
            PaymentSession.Status.CANCELLED,
            PaymentSession.Status.EXPIRED,
        }:
            s.status = PaymentSession.Status.EXPIRED
            s.save(update_fields=["status", "updated_at"])
        raise ValidationError("This payment session has expired.")
    
    # Check if session was cancelled
    if s.status == PaymentSession.Status.CANCELLED:
        raise ValidationError("This payment session was cancelled.")
    
    return s


@extend_schema(
    summary="Get hosted checkout payment status",
    description="Retrieve the current status of a checkout session including payment details and terminal state.",
    parameters=[OpenApiParameter("client_secret", str, OpenApiParameter.QUERY, required=True)],
    responses=inline_serializer(
        name="CheckoutStatus",
        fields={
            "session_id": serializers.UUIDField(),
            "session_status": serializers.CharField(),
            "payment_reference": serializers.CharField(),
            "payment_status": serializers.CharField(),
            "terminal": serializers.BooleanField(),
            "return_url": serializers.URLField(allow_blank=True),
        },
    ),
)
@api_view(["GET"])
@permission_classes([AllowAny])
def checkout_status(request, session_id):
    """
    Get the current status of a hosted checkout payment session.
    
    This endpoint retrieves detailed status information about a payment session,
    including the associated payment details and whether the payment has reached
    a terminal (final) state.
    
    Terminal states include: paid, funds_held, delivery_pending, settled, 
    failed, rejected, cancelled, expired, refunded.
    
    Args:
        request (Request): The HTTP request object
        session_id (str): The UUID of the payment session to check
        
    Returns:
        Response: JSON response with session and payment status details
        
    Raises:
        PermissionDenied: If the client secret is invalid
        ValidationError: If the session is expired or cancelled
        ObjectDoesNotExist: If the session is not found
        
    Example Response:
        {
            "session_id": "123e4567-e89b-12d3-a456-426614174000",
            "session_status": "active",
            "payment_reference": "PAY-2026-001",
            "payment_status": "pending",
            "terminal": false,
            "return_url": "https://merchant.com/return"
        }
    """
    # Extract client secret from query parameters
    client_secret = request.query_params.get("client_secret", "")
    
    # Validate and retrieve the session
    session = _session(session_id, client_secret)
    
    # Attempt to retrieve the associated payment
    try:
        payment = session.payment
    except ObjectDoesNotExist:
        payment = None
    
    # Extract payment details or use defaults
    payment_reference = payment.reference if payment else ""
    payment_status = payment.status if payment else session.status
    
    # Determine if payment has reached a terminal state
    terminal_states = {
        "paid",
        "funds_held",
        "delivery_pending",
        "settled",
        "failed",
        "rejected",
        "cancelled",
        "expired",
        "refunded",
    }
    terminal = payment_status in terminal_states
    
    # Return complete status information
    return Response(
        {
            "session_id": str(session.session_id),
            "session_status": session.status,
            "payment_reference": payment_reference,
            "payment_status": payment_status,
            "terminal": terminal,
            "return_url": session.return_url,
        }
    )