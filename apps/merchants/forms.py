from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import MerchantApplication


class MerchantApplicationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    password_confirmation = forms.CharField(widget=forms.PasswordInput, min_length=8)
    settlement_alias = forms.CharField(
        max_length=160,
        label="BurundiPay settlement alias",
        help_text="The alias where your merchant net settlements should be paid.",
    )
    settlement_account_name = forms.CharField(
        max_length=180,
        label="Registered account name",
        help_text="This must match the name registered with BurundiPay.",
    )
    consent = forms.BooleanField(
        label="I confirm this information is accurate and AmatoPay may contact me about this application."
    )
    company_website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = MerchantApplication
        fields = (
            "legal_name", "trading_name", "legal_form", "registration_number",
            "tax_id", "industry", "website", "country", "city", "address",
            "contact_name", "contact_role", "email", "phone",
            "expected_monthly_volume", "expected_monthly_transactions",
            "business_description", "payment_use_case", "settlement_alias",
            "settlement_account_name", "referral_source",
        )
        widgets = {
            "business_description": forms.Textarea(attrs={"rows": 4}),
            "payment_use_case": forms.Textarea(attrs={"rows": 4}),
            "expected_monthly_volume": forms.NumberInput(attrs={"min": "0", "step": "1"}),
            "expected_monthly_transactions": forms.NumberInput(attrs={"min": "1"}),
        }

    def clean_company_website(self):
        if self.cleaned_data.get("company_website"):
            raise forms.ValidationError("Unable to submit this application.")
        return ""

    def clean_phone(self):
        value = self.cleaned_data["phone"].strip()
        if len(value) < 7:
            raise forms.ValidationError("Enter a valid business phone number.")
        return value

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account already exists for this email. Sign in or contact Support."
            )
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password and password != cleaned.get("password_confirmation"):
            self.add_error("password_confirmation", "The passwords do not match.")
        if password:
            try:
                validate_password(password)
            except ValidationError as exc:
                self.add_error("password", exc)
        return cleaned

    def clean_settlement_alias(self):
        value = self.cleaned_data["settlement_alias"].strip()
        if len(value) < 5:
            raise forms.ValidationError("Enter a valid BurundiPay settlement alias.")
        return value
