const sessionId = JSON.parse(document.getElementById('session-id').textContent);
const clientSecret = JSON.parse(document.getElementById('client-secret').textContent);
const returnUrl = JSON.parse(document.getElementById('return-url').textContent);
const statusBox = document.getElementById('payment-status');
let pollTimer = null;

function setStatus(message, state = '') {
    statusBox.hidden = false;
    statusBox.className = `payment-status ${state}`;
    statusBox.textContent = message;
}

function returnToMerchant(paymentReference) {
    if (!returnUrl) return;
    const url = new URL(returnUrl, window.location.origin);
    if (paymentReference) url.searchParams.set('payment_reference', paymentReference);
    window.location.assign(url.toString());
}

async function parseResponse(response) {
    try {
        return await response.json();
    } catch {
        return {};
    }
}

async function pollPayment() {
    try {
        const response = await fetch(`/api/v1/checkout/sessions/${sessionId}/status/?client_secret=${encodeURIComponent(clientSecret)}`);
        const data = await parseResponse(response);
        if (response.ok && ['paid', 'funds_held', 'delivery_pending', 'settled'].includes(data.payment_status)) {
            setStatus('Payment confirmed. Returning you to the merchant…', 'success');
            window.setTimeout(() => returnToMerchant(data.payment_reference), 900);
            return;
        }
        if (response.ok && ['failed', 'rejected', 'cancelled', 'expired', 'refunded'].includes(data.payment_status)) {
            setStatus('This payment was not completed. Returning you to the merchant…', 'error');
            window.setTimeout(() => returnToMerchant(data.payment_reference), 1200);
            return;
        }
    } catch {
        setStatus('Still waiting for confirmation. Keep this page open.');
    }
    pollTimer = window.setTimeout(pollPayment, 3000);
}

pollPayment();

window.addEventListener('beforeunload', () => window.clearTimeout(pollTimer));
