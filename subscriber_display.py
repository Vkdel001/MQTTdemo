import tkinter as tk
from PIL import Image, ImageTk
import paho.mqtt.client as mqtt
import segno
from io import BytesIO

# --- MQTT Config ---
BROKER = "nodered-mqtt.bonrix.in"
PORT = 21883
USER = "nxon"
PASSWORD = "nxon1234"
TOPIC = "test1"

# --- Tkinter setup ---
root = tk.Tk()
root.title("Live QR Display")
root.geometry("300x300")  # adjust window size
label = tk.Label(root)
label.pack(padx=10, pady=10)

# Function to update QR code on the Tkinter window
def update_qr_image(qr_data):
    try:
        # Generate QR code
        qr = segno.make(qr_data, error='L')
        buffer = BytesIO()
        qr.save(buffer, kind="png", scale=8, border=2)  # specify PNG
        buffer.seek(0)

        # Load with PIL and convert to Tkinter image
        img = Image.open(buffer)
        img_tk = ImageTk.PhotoImage(img)
        label.configure(image=img_tk)
        label.image = img_tk  # keep reference
    except Exception as e:
        print("Error generating QR:", e)

# --- MQTT callbacks ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected to MQTT broker")
        client.subscribe(TOPIC)
        print(f"📡 Subscribed to topic '{TOPIC}'")
    else:
        print(f"❌ Connection failed with code {rc}")

def on_message(client, userdata, msg):
    qr_data = msg.payload.decode()
    print(f"📩 Received QR Data (length {len(qr_data)} chars)")
    update_qr_image(qr_data)

# --- MQTT client setup ---
client = mqtt.Client()
client.username_pw_set(USER, PASSWORD)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_start()  # run MQTT in background

# --- Start Tkinter loop ---
root.mainloop()
