from django import forms
from apps.merchants.models import Merchant


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
