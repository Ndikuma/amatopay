from django import forms
from django.core.validators import FileExtensionValidator


class PublicDeliveryDecisionForm(forms.Form):
    class Decision:
        CONFIRM = "confirm"
        REPORT = "report"

    decision = forms.ChoiceField(
        choices=(
            (Decision.CONFIRM, "I received it and have my AmatoPay code"),
            (Decision.REPORT, "I did not receive it or there is a problem"),
        ),
        widget=forms.RadioSelect,
        initial=Decision.CONFIRM,
    )
    secure_code = forms.RegexField(
        regex=r"^\d{6}$",
        min_length=6,
        max_length=6,
        label="Six-digit delivery code",
        required=False,
        help_text="The code you received after payment.",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}),
    )
    reason = forms.ChoiceField(
        required=False,
        choices=(
            ("not_received", "Product or service not received"),
            ("incomplete", "Delivery was incomplete"),
            ("not_as_described", "Not as described"),
            ("damaged", "Damaged or unusable"),
            ("other", "Another delivery problem"),
        ),
    )
    description = forms.CharField(
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Do not include passwords, PINs, or payment credentials.",
    )
    evidence_file = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(["pdf", "png", "jpg", "jpeg", "txt"])],
        help_text="Optional PDF, PNG, JPG, or text proof (max 5 MB).",
    )

    def clean(self):
        cleaned = super().clean()
        decision = cleaned.get("decision")
        if not cleaned.get("secure_code"):
            self.add_error("secure_code", "Enter your six-digit delivery code.")

        if decision == self.Decision.REPORT:
            if not cleaned.get("reason"):
                self.add_error("reason", "Select what went wrong.")
            if not cleaned.get("description", "").strip():
                self.add_error("description", "Please tell us what happened.")
        return cleaned

    def clean_evidence_file(self):
        evidence = self.cleaned_data.get("evidence_file")
        if evidence and evidence.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Evidence files must be 5 MB or smaller.")
        allowed_types = {
            "application/pdf",
            "image/png",
            "image/jpeg",
            "text/plain",
        }
        if evidence and evidence.content_type not in allowed_types:
            raise forms.ValidationError("Upload a PDF, PNG, JPG, or text file.")
        return evidence
