import requests
import segno
import paho.mqtt.client as mqtt

# ==== MQTT CONFIG ====
BROKER = "nodered-mqtt.bonrix.in"
PORT = 21883
USERNAME = "nxon"
PASSWORD = "nxon1234"
TOPIC = "test1"

# ==== API CONFIG ====
API_URL = "https://apiuat.zwennpay.com:9425/api/v1.0/Common/GetMerchantQR"

def generate_qr_code(amount: float):
    """
    Call the API to generate QR code data
    and return the QR string.
    """
    payload = {
        "MerchantId": 57,
        "SetTransactionAmount": True,
        "TransactionAmount": str(amount),   # static test amount
        "SetConvenienceIndicatorTip": False,
        "ConvenienceIndicatorTip": 0,
        "SetConvenienceFeeFixed": False,
        "ConvenienceFeeFixed": 0,
        "SetConvenienceFeePercentage": False,
        "ConvenienceFeePercentage": 0,
    }

    try:
        response = requests.post(
            API_URL,
            headers={"accept": "text/plain", "Content-Type": "application/json"},
            json=payload,
            timeout=20
        )

        if response.status_code == 200:
            qr_data = str(response.text).strip()
            if not qr_data or qr_data.lower() in ("null", "none", "nan"):
                print("⚠️ No valid QR data received from API")
                return None
            return qr_data
        else:
            print(f"❌ API request failed: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        print(f"❌ Error calling API: {e}")
        return None


def publish_to_mqtt(qr_data: str):
    """
    Publish QR data to MQTT broker.
    """
    try:
        client = mqtt.Client()
        client.username_pw_set(USERNAME, PASSWORD)
        client.connect(BROKER, PORT, 60)

        # Publish QR code string (retain last message for late subscribers)
        client.publish(TOPIC, qr_data, retain=True)
        print(f"✅ QR Code data published to topic '{TOPIC}'")

        client.disconnect()
    except Exception as e:
        print(f"❌ Error publishing to MQTT: {e}")


if __name__ == "__main__":
    # Use a static amount for testing
    amount = 123.45

    # Step 1: Get QR data from API
    qr_data = generate_qr_code(amount)
    if qr_data:
        print("QR Data from API:", qr_data[:80], "...")  # show first 80 chars for debugging

        # Step 2: Save QR code locally (optional)
        qr = segno.make(qr_data, error="L")
        qr_filename = "test_qr.png"
        qr.save(qr_filename, scale=8, border=2, dark="#000000")
        print(f"✅ QR Code saved as {qr_filename}")

        # Step 3: Send QR code data to MQTT broker
        publish_to_mqtt(qr_data)
