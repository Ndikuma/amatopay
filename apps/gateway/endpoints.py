"""MobileCash/CECF endpoint paths used by the BurundiPay gateway."""

LOGIN = "/api/external/login"
ALIAS_VERIFY = "/api/alias/verify"
COLLECTION_CREATE = "/api/MobileTrxPay/rtp"
P2P_CREATE = "/api/MobileTrxPay/p2p"
TRANSACTION_BY_REFERENCE = "/api/MobileTrxPay/reference/{reference}"
TRANSACTIONS_PAGED = "/api/MobileTrxPay/paged"
SEND_SMS = "/api/Notifications/sms"

# QR — payer scans AmatoPay's own registered code; AmatoPay never initiates
# the debit, it only watches for a matching transaction.
QR_SCAN = "/api/IpsQr/scan"
QR_SCAN_STATUS = "/api/IpsQr/scan/status"
