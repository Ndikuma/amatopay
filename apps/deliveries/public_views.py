from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import APIException

from apps.payments.models import Payment
from .forms import PublicDeliveryDecisionForm
from .services import confirm_delivery_with_code, open_customer_delivery_claim

