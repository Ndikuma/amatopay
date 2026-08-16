from django import forms

class PlanRequestForm(forms.Form):
    payer_alias = forms.CharField(
        label="Your BurundiPay mobile money number",
        max_length=60,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g., 25779123456",
            "class": "block w-full px-4 py-3 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
        }),
    )
    note = forms.CharField(
        label="Optional note",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": "block w-full px-4 py-3 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
        }),
        required=False,
    )
