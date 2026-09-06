"""MobileCash/CECF endpoint paths used by the BurundiPay gateway."""

LOGIN = "/api/external/login"
ALIAS_VERIFY = "/api/alias/verify"
COLLECTION_CREATE = "/api/MobileTrxPay/rtp"
P2P_CREATE = "/api/MobileTrxPay/p2p"
TRANSACTION_BY_REFERENCE = "/api/MobileTrxPay/reference/{reference}"
SEND_SMS = "/api/Notifications/sms"
