from django import forms
from django.core.validators import FileExtensionValidator


ACCEPTANCE_PROOF_CHOICES = (
    ("signed_delivery_note", "Signed delivery note"),
    ("receipt_or_invoice", "Receipt or invoice"),
    ("photo_or_screenshot", "Photo or screenshot"),
    ("service_acceptance", "Service acceptance document"),
    ("other", "Other supporting proof"),
)


EVIDENCE_HELP_TEXT = (
    "Optional PDF, PNG, JPG, or text proof: receipt, photo, delivery note, "
    "or service-acceptance document."
)


class PublicDeliveryDecisionForm(forms.Form):
    class Decision:
        CONFIRM = "confirm"
        REPORT = "report"
        REVIEW = "review"

    decision = forms.ChoiceField(
        choices=(
            (Decision.CONFIRM, "I received it and have my AmatoPay code"),
            (Decision.REVIEW, "I received it but need another proof method"),
            (Decision.REPORT, "I did not receive it or there is a problem"),
        ),
        widget=forms.RadioSelect,
    )
    secure_code = forms.RegexField(
        regex=r"^\d{6}$",
        min_length=6,
        max_length=6,
        label="Six-digit delivery code",
        required=False,
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}
        ),
    )
    payer_alias = forms.CharField(
        required=False,
        max_length=160,
        label="Payer mobile number or alias",
        help_text="Use the same payer alias used for this payment.",
    )
    proof_method = forms.ChoiceField(
        required=False,
        label="Proof method",
        choices=ACCEPTANCE_PROOF_CHOICES,
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
        help_text=EVIDENCE_HELP_TEXT,
    )

    def clean(self):
        cleaned = super().clean()
        decision = cleaned.get("decision")
        if decision == self.Decision.CONFIRM and not cleaned.get("secure_code"):
            self.add_error("secure_code", "Enter the code for immediate confirmation.")
        if decision in {self.Decision.REPORT, self.Decision.REVIEW}:
            if not cleaned.get("secure_code") and not cleaned.get("payer_alias", "").strip():
                self.add_error(
                    "payer_alias",
                    "Enter either your delivery code or the payer alias used for payment.",
                )
        if decision == self.Decision.REVIEW:
            if not cleaned.get("proof_method"):
                self.add_error("proof_method", "Select the proof you can provide.")
        if decision == self.Decision.REPORT:
            if not cleaned.get("reason"):
                self.add_error("reason", "Select what went wrong.")
        if decision in {self.Decision.REPORT, self.Decision.REVIEW} and not cleaned.get(
            "description", ""
        ).strip():
            self.add_error("description", "Tell us what happened.")
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
