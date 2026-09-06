const body = document.body;

document.querySelector('[data-open-menu]')?.addEventListener('click', () => {
    body.classList.add('menu-open');
});

document.querySelectorAll('[data-close-menu]').forEach((element) => {
    element.addEventListener('click', () => body.classList.remove('menu-open'));
});

const search = document.querySelector('[data-table-search]');
const rows = document.querySelectorAll('[data-search-table] tbody tr');
const filterButtons = document.querySelectorAll('[data-status-filter]');
const filteredEmpty = document.querySelector('[data-filtered-empty]');
let activeStatus = 'all';

const filterRows = () => {
    const query = search?.value.trim().toLowerCase() || '';
    let visible = 0;
    rows.forEach((row) => {
        const matchesSearch = !query || row.textContent.toLowerCase().includes(query);
        const status = row.dataset.paymentStatus;
        const successful = ['paid', 'funds_held', 'delivery_pending', 'release_pending', 'settlement_processing', 'settled'].includes(status);
        const processing = ['created', 'alias_verified', 'rtp_pending', 'awaiting_approval', 'processing'].includes(status);
        const failed = ['failed', 'rejected', 'cancelled', 'reversed', 'expired', 'fraud_blocked'].includes(status);
        const matchesStatus = activeStatus === 'all' || (activeStatus === 'paid' && successful) || (activeStatus === 'processing' && processing) || (activeStatus === 'failed' && failed);
        row.hidden = !(matchesSearch && matchesStatus);
        if (!row.hidden) visible += 1;
    });
    if (filteredEmpty) filteredEmpty.hidden = visible > 0;
};

search?.addEventListener('input', filterRows);
filterButtons.forEach((button) => button.addEventListener('click', () => {
    activeStatus = button.dataset.statusFilter;
    filterButtons.forEach((item) => item.classList.toggle('is-active', item === button));
    filterRows();
}));

const toast = document.querySelector('[data-toast]');
let toastTimer;
const showToast = (message) => {
    if (!toast) return;
    toast.querySelector('[data-toast-message]').textContent = message;
    toast.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 2200);
};

document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(button.dataset.copy);
            showToast('Payment reference copied');
        } catch (_) {
            showToast('Could not copy reference');
        }
    });
});

document.querySelectorAll('[data-copy-secret]').forEach((button) => {
    button.addEventListener('click', async () => {
        const scope = button.closest('.secret-reveal') || document;
        const value = scope.querySelector('[data-secret-value]')?.textContent.trim();
        if (!value) return;
        try {
            await navigator.clipboard.writeText(value);
            button.textContent = 'Copied';
            showToast('Secret copied to clipboard');
        } catch (_) {
            showToast('Could not copy — select and copy manually');
        }
    });
});