from django.shortcuts import get_object_or_404, render
from apps.checkout.models import PaymentSession


def pay(request, session_id):
    s = get_object_or_404(
        PaymentSession.objects.select_related("merchant"), session_id=session_id
    )
    return render(request, "checkout/pay.html", {"session": s, "merchant": s.merchant})


def home(request):
    return render(request, "portal/home.html")


def docs(request):
    return render(request, "portal/docs.html")
