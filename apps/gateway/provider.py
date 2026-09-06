"""Client for the MobileCash API used by BurundiPay/CECF."""

import threading
import time
from datetime import datetime
from decimal import Decimal
from typing import Any

import requests

from . import endpoints


class MobileCashGatewayError(Exception):
    def __init__(self, operation: str, status_code: int, body: str):
        self.operation = operation
        self.status_code = status_code
        self.body = body
        super().__init__(f"MobileCash {operation} [{status_code}]: {body[:200]}")


class MobileCashGateway:
    """Authenticated, reusable MobileCash gateway with a thread-safe JWT cache."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        creditor_alias: str,
        timeout: int = 15,
        verify_tls: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.creditor_alias = creditor_alias
        self.timeout = timeout
        self.verify_tls = verify_tls
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()
        self._session = requests.Session()

    @staticmethod
    def _parse_expiry(value: str) -> float:
        if not value:
            return time.time() + 3600
        if "." in value:
            head, fraction = value.split(".", 1)
            value = f"{head}.{fraction[:6]}"
        try:
            expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                return time.time() + max(
                    (expires_at - datetime.now()).total_seconds(), 60
                )
            return expires_at.timestamp()
        except ValueError:
            return time.time() + 3600

    def _refresh_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        with self._token_lock:
            if self._token and time.time() < self._token_expires_at - 30:
                return self._token
            try:
                response = self._session.post(
                    f"{self.base_url}{endpoints.LOGIN}",
                    json={"username": self.username, "password": self.password},
                    timeout=self.timeout,
                    verify=self.verify_tls,
                )
                self._raise_for_error(response, "login")
            except requests.RequestException as exc:
                raise MobileCashGatewayError("login", 503, str(exc)) from exc
            data = response.json()
            self._token = data["jwt"]
            self._token_expires_at = self._parse_expiry(data.get("jwtExpiresAt", ""))
            return self._token

    def authenticate(self) -> str:
        """Authenticate immediately; used by the admin connection test."""
        self._token = None
        self._token_expires_at = 0
        return self._refresh_token()

    def _request(
        self, method: str, path: str, operation: str, **kwargs
    ) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._refresh_token()}"
        headers.setdefault("Accept", "application/json")
        try:
            response = self._session.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_tls,
                **kwargs,
            )
            if response.status_code == 401:
                self._token = None
                headers["Authorization"] = f"Bearer {self._refresh_token()}"
                response = self._session.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    timeout=self.timeout,
                    verify=self.verify_tls,
                    **kwargs,
                )
            self._raise_for_error(response, operation)
            return response.json() if response.content else {}
        except requests.RequestException as exc:
            raise MobileCashGatewayError(operation, 503, str(exc)) from exc

    @staticmethod
    def _raise_for_error(response, operation: str) -> None:
        if response.ok:
            return
        raise MobileCashGatewayError(operation, response.status_code, response.text)

    def verify_alias(self, alias: str, alias_type: str = "MOBILE") -> dict[str, Any]:
        try:
            result = self._request(
                "POST",
                endpoints.ALIAS_VERIFY,
                "alias.verify",
                json={"alias": alias, "aliasType": alias_type},
            )
        except MobileCashGatewayError as exc:
            if exc.status_code == 404:
                return {"found": False, "status": "NOT_FOUND"}
            raise

        verified = bool(result.get("isVerified", False))
        can_debit = bool(result.get("canDebit", False))
        full_name = result.get("fullName") or result.get("name") or ""
        account_number = self._find(
            result,
            "defaultAccount",
            "accountNumber",
            "accountNo",
            "account_number",
            "iban",
        ) or ""
        account_name = self._find(result, "accountName", "account_name") or full_name
        return {
            "found": True,
            "status": "ACTIVE" if verified and can_debit else "INACTIVE",
            "customer": {
                "name": full_name,
                "reference": str(result.get("rowid") or result.get("id") or ""),
            },
            "account": {
                "type": result.get("aliasType", alias_type),
                "account_type": result.get("accountType", ""),
                "currency": result.get("currency", "BIF"),
                "number": str(account_number),
                "name": str(account_name),
                "servicer_code": result.get("servicerCode", ""),
                "servicer_code_type": result.get("servicerCodeType", ""),
            },
            "provider": result,
        }

    def create_collection(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.creditor_alias:
            raise MobileCashGatewayError(
                "collection.create",
                0,
                "The active gateway creditor_alias is required for collection",
            )
        amount = Decimal(str(payload.get("totalAmount") or payload["amount"]))
        result = self._request(
            "POST",
            endpoints.COLLECTION_CREATE,
            "collection.create",
            json={
                "creditorAlias": self.creditor_alias,
                "debtorAlias": payload["payerAlias"],
                "amount": float(amount),
                "description": payload.get("order", {}).get("description")
                or payload.get("paymentReference"),
            },
        )
        reference = self._find(result, "trxRef", "trxref")
        if not reference:
            raise MobileCashGatewayError(
                "collection.create", 502, "Gateway response did not contain trxRef"
            )
        status = self._find(result, "status") or "PENDING"
        return {
            "requestId": payload["requestId"],
            "trxRef": str(reference),
            "status": self.normalize_status(status),
            "provider": result,
        }

    def create_p2p(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Pay released fiduciary funds from AmatoPay to a verified merchant alias."""
        if not self.creditor_alias:
            raise MobileCashGatewayError(
                "p2p.create",
                0,
                "The AmatoPay fiduciary/collection alias is required for P2P payouts",
            )
        beneficiary = payload.get("beneficiary") or {}
        alias_type = str(beneficiary.get("aliasType", "MOBILE")).upper()
        receiver_alias = beneficiary.get("alias")
        if not receiver_alias:
            raise MobileCashGatewayError(
                "p2p.create", 0, "Merchant receiver alias is required"
            )
        if alias_type != "MOBILE":
            raise MobileCashGatewayError(
                "p2p.create", 0, "Merchant receiver alias must be a MOBILE alias"
            )
        if receiver_alias.strip() == self.creditor_alias.strip():
            raise MobileCashGatewayError(
                "p2p.create",
                0,
                "Merchant receiver alias must differ from the AmatoPay fiduciary alias",
            )
        amount = Decimal(str(payload["amount"]))
        result = self._request(
            "POST",
            endpoints.P2P_CREATE,
            "p2p.create",
            json={
                "payerAlias": self.creditor_alias,
                "receiverAlias": receiver_alias,
                "amount": float(amount),
                "description": payload.get("description")
                or f"AmatoPay settlement {payload.get('settlementReference', '')}",
            },
        )
        reference = self._find(result, "trxRef", "trxref")
        if not reference:
            raise MobileCashGatewayError(
                "p2p.create", 502, "Gateway response did not contain trxRef"
            )
        status = self._find(result, "status") or "PROCESSING"
        return {
            "requestId": payload["requestId"],
            "trxRef": str(reference),
            "status": self.normalize_status(status),
            "provider": result,
        }

    def send_sms(self, phone_number: str, message: str) -> dict[str, Any]:
        """Send an SMS notification to a customer."""
        payload = {
            "phoneNumber": phone_number,
            "message": message,
            "notificationCode": "PIN",
        }
        return self._request(
            "POST",
            endpoints.SEND_SMS,
            "sms.send",
            json=payload,
        )

    def get_transaction(self, reference: str) -> dict[str, Any]:
        result = self._request(
            "GET",
            endpoints.TRANSACTION_BY_REFERENCE.format(reference=reference),
            "transaction.get",
        )
        returned_reference = self._find(result, "trxRef", "trxref")
        if returned_reference and str(returned_reference) != str(reference):
            raise MobileCashGatewayError(
                "transaction.get",
                502,
                f"Gateway returned trxRef {returned_reference} for requested {reference}",
            )
        status = self._find(result, "status") or "PENDING"
        reason = self._find(
            result, "reasonCode", "statusDescription", "descrResp"
        ) or ""
        return {
            "trxRef": str(reference),
            "status": self.normalize_status(status),
            "reasonCode": str(reason),
            "provider": result,
        }

    @classmethod
    def _find(cls, value: Any, *keys: str) -> Any:
        if not isinstance(value, dict):
            return None
        for key in keys:
            if value.get(key) not in (None, ""):
                return value[key]
        for container in ("rtp", "transaction", "data", "result"):
            found = cls._find(value.get(container), *keys)
            if found not in (None, ""):
                return found
        return None

    @staticmethod
    def normalize_status(status: str) -> str:
        normalized = str(status).strip().upper().replace("-", "_").replace(" ", "_")
        mapping = {
            "SUCCESS": "COMPLETED",
            "SUCCESSFUL": "COMPLETED",
            "SETTLED": "COMPLETED",
            "ACCEPTED": "PROCESSING",
            "APPROVED": "PROCESSING",
            "AWAITING": "AWAITING_APPROVAL",
            "AWAITINGPAYERDECISION": "AWAITING_APPROVAL",
            "DECLINED": "REJECTED",
            "EXPIRED": "FAILED",
        }
        return mapping.get(normalized, normalized)
