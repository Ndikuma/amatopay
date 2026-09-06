from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.merchants.models import Merchant, MerchantApplication


class PlanRequestForm(forms.Form):
    payer_alias = forms.CharField(
        label="Your BurundiPay mobile money number",
        max_length=60,
        widget=forms.TextInput(attrs={"placeholder": "e.g., 25779123456"}),
    )
    note = forms.CharField(
        label="Optional note",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
    )


MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

ALL_DOCUMENT_FIELDS = (
    "registration_document",
    "tax_document",
    "license_document",
    "address_document",
    "id_document",
    "bank_document",
)
# Only these two are needed to start the review — the rest can be added during
# onboarding, since merchants rarely have every document ready at once.
REQUIRED_DOCUMENT_FIELDS = ("registration_document", "id_document")


class MerchantApplicationForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput, min_length=8,
        help_text="Your AmatoPay dashboard password — never your bank PIN or OTP.",
    )
    password_confirmation = forms.CharField(widget=forms.PasswordInput, min_length=8)
    settlement_alias = forms.CharField(
        max_length=160,
        label="BurundiPay settlement alias",
        help_text="The mobile money number where your net settlements should be paid.",
    )
    settlement_account_name = forms.CharField(
        max_length=180,
        label="Registered account name",
        help_text="Must match the name registered with BurundiPay for that number.",
    )
    consent = forms.BooleanField(
        label="I confirm this information is accurate and AmatoPay may contact me about this application."
    )
    company_website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = MerchantApplication
        fields = (
            "legal_name", "trading_name", "legal_form", "registration_number",
            "tax_id", "industry", "mcc", "website", "country", "city", "address",
            "contact_name", "contact_role", "email", "phone",
            "expected_monthly_volume", "expected_monthly_transactions",
            "business_description", "payment_use_case", "source_of_funds",
            "settlement_alias", "settlement_account_name", "statement_descriptor",
            "registration_document", "tax_document", "license_document",
            "address_document", "id_document", "bank_document",
            "referral_source",
        )
        widgets = {
            "business_description": forms.Textarea(attrs={"rows": 4}),
            "payment_use_case": forms.Textarea(attrs={"rows": 4}),
            "expected_monthly_volume": forms.NumberInput(attrs={"min": "0", "step": "1"}),
            "expected_monthly_transactions": forms.NumberInput(attrs={"min": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("registration_number", "tax_id", "source_of_funds", *REQUIRED_DOCUMENT_FIELDS):
            self.fields[name].required = True
        for name in ("trading_name", "website", "mcc", "statement_descriptor", "referral_source"):
            self.fields[name].required = False
        optional_docs = set(ALL_DOCUMENT_FIELDS) - set(REQUIRED_DOCUMENT_FIELDS)
        for name in optional_docs:
            self.fields[name].required = False
            self.fields[name].help_text = (
                "Optional now — you can upload this during onboarding."
            )

    def _clean_upload(self, field_name):
        upload = self.cleaned_data.get(field_name)
        if not upload or not getattr(upload, "name", ""):
            return upload
        if upload.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError("Each document must be 8 MB or smaller.")
        suffix = "." + upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
        if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
            raise forms.ValidationError("Upload a PDF or an image (PNG, JPG, WEBP).")
        return upload

    def clean_registration_document(self):
        return self._clean_upload("registration_document")

    def clean_tax_document(self):
        return self._clean_upload("tax_document")

    def clean_license_document(self):
        return self._clean_upload("license_document")

    def clean_address_document(self):
        return self._clean_upload("address_document")

    def clean_id_document(self):
        return self._clean_upload("id_document")

    def clean_bank_document(self):
        return self._clean_upload("bank_document")

    def clean_company_website(self):
        if self.cleaned_data.get("company_website"):
            raise forms.ValidationError("Unable to submit this application.")
        return ""

    def clean_phone(self):
        value = self.cleaned_data["phone"].strip()
        if len(value) < 7:
            raise forms.ValidationError("Enter a valid business phone number.")
        return value

    def clean_statement_descriptor(self):
        return self.cleaned_data.get("statement_descriptor", "").strip()[:22]

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


class MerchantMissingProfileForm(forms.ModelForm):
    class Meta:
        model = Merchant
        fields = (
            "legal_form",
            "registration_number",
            "tax_id",
            "website",
            "statement_descriptor",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields = {
            name: field
            for name, field in self.fields.items()
            if not getattr(self.instance, name)
        }

class DeliveryCodeConfirmationForm(forms.Form):
    payment_reference = forms.CharField(max_length=64)
    secure_code = forms.RegexField(
        regex=r"^\d{6}$",
        min_length=6,
        max_length=6,
        widget=forms.PasswordInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9]{6}",
                "placeholder": "6-digit delivery code",
            }
        ),
    )

    def __init__(self, *args, expected_reference, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_reference = expected_reference
        self.fields["payment_reference"].widget.attrs.update(
            {"autocomplete": "off", "spellcheck": "false"}
        )

    def clean_payment_reference(self):
        reference = self.cleaned_data["payment_reference"].strip().upper()
        if reference != self.expected_reference:
            raise forms.ValidationError("Payment reference does not match this payment.")
        return reference
