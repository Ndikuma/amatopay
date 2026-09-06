"""Read-only fiduciary inlines surfaced on the Payment admin.

Kept separate from ``fiduciary.admin`` so that ``payments.admin`` can import
these classes without triggering admin registration side effects or depending
on admin autodiscovery order.
"""

from unfold.admin import TabularInline

from .models import FiduciaryEntry, FundHold


class FundHoldInline(TabularInline):
    model = FundHold
    fields = ("amount", "status", "held_at", "release_eligible_at", "released_at")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class FiduciaryEntryInline(TabularInline):
    model = FiduciaryEntry
    fields = ("direction", "kind", "amount", "reference", "created_at")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False
