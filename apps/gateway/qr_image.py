"""Render AmatoPay's own registered QR payload as a displayable image.

Only rendering is needed here — unlike burundipay-checkout, AmatoPay never
decodes a merchant-uploaded QR photo, since there is exactly one shared code
(``GatewayConfig.qr_code_text``) for every QR-enabled merchant.
"""

import base64
import io

import qrcode


def generate_qr_data_uri(qr_code_text: str) -> str:
    """Return AmatoPay's QR as a base64 PNG data URI for inline <img> use."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_code_text)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#071c27", back_color="#ffffff").convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
