import paho.mqtt.client as mqtt
import segno

# ==== MQTT CONFIG ====
BROKER = "nodered-mqtt.bonrix.in"
PORT = 21883
USERNAME = "nxon"
PASSWORD = "nxon1234"
TOPIC = "test1"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected to MQTT broker")
        client.subscribe(TOPIC)
        print(f"📡 Subscribed to topic: {TOPIC}")
    else:
        print(f"❌ Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    qr_data = msg.payload.decode()
    print(f"📩 Received QR Data (length {len(qr_data)} chars)")

    try:
        # Re-generate QR code from received data
        qr = segno.make(qr_data, error="L")
        qr_filename = "received_qr.png"
        qr.save(qr_filename, scale=8, border=2, dark="#000000")
        print(f"✅ QR code saved as {qr_filename}")
    except Exception as e:
        print(f"❌ Error creating QR: {e}")

def main():
    client = mqtt.Client()
    client.username_pw_set(USERNAME, PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, 60)
    client.loop_forever()

if __name__ == "__main__":
    main()
