import requests
import base64
import os
import uuid

PAYHERO_BASE_URL = "https://backend.payhero.co.ke/api/v2"

def get_auth_header():
    """Generate Basic Auth header from env credentials"""
    username = os.getenv("PAYHERO_USERNAME")
    password = os.getenv("PAYHERO_PASSWORD")
    credentials = f"{username}:{password}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"

def initiate_stk_push(phone_number, amount, external_reference, customer_name="SmartRent Tenant"):
    """
    Trigger M-Pesa STK Push via PayHero
    
    Args:
        phone_number: e.g. "0712345678" or "254712345678"
        amount: integer e.g. 25000
        external_reference: unique ID for this transaction e.g. "RENT-A45-MAR2025"
        customer_name: tenant's name
    
    Returns:
        dict with keys: success, reference, checkout_request_id, error
    """
    # Normalize phone number to 254 format
    phone = normalize_phone(phone_number)
    
    payload = {
        "amount": int(amount),
        "phone_number": phone,
        "channel_id": int(os.getenv("PAYHERO_CHANNEL_ID")),
        "provider": "m-pesa",
        "external_reference": external_reference,
        "customer_name": customer_name,
        "callback_url": os.getenv("PAYHERO_CALLBACK_URL")
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": get_auth_header()
    }
    
    try:
        response = requests.post(
            f"{PAYHERO_BASE_URL}/payments",
            json=payload,
            headers=headers,
            timeout=30
        )
        data = response.json()
        
        if response.status_code == 200 and data.get("success"):
            return {
                "success": True,
                "reference": data.get("reference"),          # PayHero reference e.g. "E8UWT7CLUW"
                "checkout_request_id": data.get("CheckoutRequestID"),
                "status": data.get("status")                 # "QUEUED"
            }
        else:
            return {
                "success": False,
                "error": data.get("message", "Payment initiation failed")
            }
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out. Try again."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_transaction_status(reference):
    """Check status of a transaction by PayHero reference"""
    headers = {"Authorization": get_auth_header()}
    
    response = requests.get(
        f"{PAYHERO_BASE_URL}/transaction-status",
        params={"reference": reference},
        headers=headers,
        timeout=15
    )
    return response.json()


def normalize_phone(phone):
    """Convert any Kenyan phone format to 254XXXXXXXXX"""
    phone = str(phone).strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith("0"):
        phone = "254" + phone[1:]
    if phone.startswith("7") or phone.startswith("1"):
        phone = "254" + phone
    return phone


def generate_reference(tenant_id, bill_type):
    """Generate a unique external reference for a transaction"""
    short_id = str(uuid.uuid4())[:8].upper()
    return f"SR-{tenant_id}-{bill_type[:4].upper()}-{short_id}"