from flask import Flask, request, jsonify, Response, render_template
from flask_cors import CORS
import threading
import json
import time
import uuid
from datetime import datetime

import requests
import segno
import paho.mqtt.client as mqtt

app = Flask(__name__)
CORS(app) 

# MQTT broker config
BROKER = "nodered-mqtt.bonrix.in"
PORT = 31883
USER = "bonrix"
PASSWORD = "bonrix123456789"
TOPIC = "F0F5BD759280"

# BHIM Device config
BHIM_DEVICE_IP = "192.168.100.73"
BHIM_DEVICE_URL = f"http://{BHIM_DEVICE_IP}"

# In-memory storage for current QR data (thread-safe)
qr_data_lock = threading.Lock()
current_qr_data = {
    "qr_data": None,
    "amount": None,
    "timestamp": None
}

# SSE client management
sse_clients = {}  # Dictionary to store client_id -> client_info
sse_clients_lock = threading.Lock()

class SSEClient:
    def __init__(self, client_id):
        self.client_id = client_id
        self.queue = []
        self.queue_lock = threading.Lock()
        self.connected = True
        self.last_heartbeat = time.time()
    
    def add_message(self, message):
        """Add message to client queue"""
        with self.queue_lock:
            self.queue.append(message)
    
    def get_messages(self):
        """Get and clear all messages from queue"""
        with self.queue_lock:
            messages = self.queue.copy()
            self.queue.clear()
            return messages
    
    def disconnect(self):
        """Mark client as disconnected"""
        self.connected = False

# MQTT message callback to capture QR data
def on_message(client, userdata, msg):
    """Handle incoming MQTT messages and store QR data"""
    try:
        payload = msg.payload.decode()
        timestamp = datetime.now().isoformat()
        
        # Try to parse as JSON first (new format with amount)
        try:
            mqtt_data = json.loads(payload)
            qr_data = mqtt_data.get("qr_data")
            amount = mqtt_data.get("amount")
            print(f"📩 Received MQTT JSON: QR={len(qr_data)} chars, Amount={amount}")
        except json.JSONDecodeError:
            # Fallback to old format (plain QR string)
            qr_data = payload
            amount = current_qr_data.get("amount")  # Use stored amount as fallback
            print(f"📩 Received MQTT plain text: {len(qr_data)} chars")
        
        # Thread-safe update of current QR data
        with qr_data_lock:
            current_qr_data["qr_data"] = qr_data
            current_qr_data["amount"] = amount
            current_qr_data["timestamp"] = timestamp
        
        # Broadcast to SSE clients and BHIM device with correct amount
        broadcast_qr_update(qr_data, amount)
        
    except Exception as e:
        print(f"❌ Error handling MQTT message: {e}")

def on_connect(client, userdata, flags, rc):
    """Handle MQTT connection"""
    if rc == 0:
        print("✅ Connected to MQTT broker")
        client.subscribe(TOPIC)
        print(f"📡 Subscribed to topic '{TOPIC}'")
    else:
        print(f"❌ MQTT connection failed with code {rc}")

def on_disconnect(client, userdata, rc):
    """Handle MQTT disconnection"""
    print(f"📡 Disconnected from MQTT broker (code: {rc})")

def wake_up_bhim_device():
    """Wake up BHIM device by putting it into Dynamic QR API mode (status=2)"""
    try:
        # Create a session to maintain cookies/state like browser
        session = requests.Session()
        
        # Browser-like headers to mimic browser behavior
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'close',  # Changed to close to avoid connection reuse issues
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0'
        }
        
        # First, try to access the main page to establish session
        try:
            print("🔄 Establishing session with BHIM device...")
            main_response = session.get(
                f"{BHIM_DEVICE_URL}/",
                headers=headers,
                timeout=15,
                verify=False,  # Disable SSL verification
                allow_redirects=True
            )
            print(f"📄 Main page response: {main_response.status_code}")
        except Exception as session_e:
            print(f"⚠️ Session establishment failed: {session_e}")
        
        # Now try the wake-up call with the session
        response = session.get(
            f"{BHIM_DEVICE_URL}/home?status=2",
            headers=headers,
            timeout=30,
            verify=False,  # Disable SSL verification
            allow_redirects=True
        )
        
        # Wake-up call returns HTML page (200 status), not "ok"
        if response.status_code == 200:
            print("✅ BHIM device activated in Dynamic QR API mode")
            # Give device time to fully initialize API endpoints
            print("⏳ Waiting for device to initialize API endpoints...")
            time.sleep(5)
            return True
        else:
            print(f"⚠️ BHIM device wake-up responded with status {response.status_code}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"⏰ BHIM device wake-up timeout (device might still be activating)")
        # Even if timeout, device might still activate, so wait and return True
        print("⏳ Waiting for device to complete initialization...")
        time.sleep(8)
        return True
    except requests.exceptions.ConnectionError as ce:
        print(f"❌ Connection error waking up BHIM device: {ce}")
        # Try alternative approach - assume device will activate anyway
        print("⏳ Assuming device is activating, waiting...")
        time.sleep(10)
        return True
    except Exception as e:
        print(f"❌ Error waking up BHIM device: {e}")
        return False

def send_with_auto_recovery(endpoint, params, operation_name):
    """Send request to BHIM device with automatic recovery on 404 errors"""
    try:
        # Browser-like headers for API calls too
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive'
        }
        
        response = requests.get(
            f"{BHIM_DEVICE_URL}{endpoint}",
            params=params,
            headers=headers,
            timeout=15  # Increased timeout for API calls
        )
        
        # If 404 or timeout, try to wake up device and retry once
        if response.status_code == 404:
            print(f"🔄 BHIM device not ready (404), attempting wake-up for {operation_name}")
            if wake_up_bhim_device():
                # Retry the original request with longer timeout
                print(f"🔄 Retrying {operation_name} after wake-up...")
                response = requests.get(
                    f"{BHIM_DEVICE_URL}{endpoint}",
                    params=params,
                    headers=headers,
                    timeout=15
                )
        
        if response.status_code == 200 and response.text.strip().lower() == "ok":
            print(f"✅ {operation_name} sent to BHIM device successfully")
            return True
        else:
            print(f"⚠️ BHIM device responded with status {response.status_code}, response: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to BHIM device at {BHIM_DEVICE_IP}")
        return False
    except requests.exceptions.Timeout:
        print(f"⏰ Timeout connecting to BHIM device for {operation_name}")
        # On timeout, try wake-up and retry once
        print(f"🔄 Attempting wake-up due to timeout for {operation_name}")
        if wake_up_bhim_device():
            try:
                print(f"🔄 Retrying {operation_name} after timeout wake-up...")
                response = requests.get(
                    f"{BHIM_DEVICE_URL}{endpoint}",
                    params=params,
                    headers=headers,
                    timeout=20  # Even longer timeout for retry
                )
                
                if response.status_code == 200 and response.text.strip().lower() == "ok":
                    print(f"✅ {operation_name} sent to BHIM device successfully (after timeout recovery)")
                    return True
                else:
                    print(f"⚠️ BHIM device responded with status {response.status_code} after timeout recovery")
                    return False
                    
            except Exception as retry_e:
                print(f"❌ Retry after timeout failed for {operation_name}: {retry_e}")
                return False
        else:
            return False
    except Exception as e:
        print(f"❌ Error sending {operation_name} to BHIM device: {e}")
        return False

def send_welcome_to_bhim_device(title="Welcome to ZwennPay", img=""):
    """Send welcome message to BHIM device"""
    params = {
        "img": img,
        "title": title
    }
    
    return send_with_auto_recovery("/DisplayWelcomeMessage", params, "welcome message")

def send_total_to_bhim_device(total_amount, discount=0, tax=0, grand_total=None):
    """Send total amount display to BHIM device"""
    if grand_total is None:
        grand_total = float(total_amount) - float(discount) + float(tax)
    
    params = {
        "img": "",
        "totalamount": str(total_amount),
        "savingdiscount": str(discount),
        "taxamount": str(tax),
        "grandtotal": str(grand_total)
    }
    
    return send_with_auto_recovery("/DisplayTotal", params, "total display")

def send_qr_to_bhim_device(qr_data, amount=None):
    """Send QR code to BHIM device for display using correct API endpoint"""
    import base64
    
    # Convert QR data to base64 (BHIM device expects base64 encoded QR)
    qr_base64 = base64.b64encode(qr_data.encode()).decode()
    
    # Prepare parameters for BHIM device API
    params = {
        "qrcodebase64": qr_base64,
        "upiurl": qr_data,  # Original UPI URL
        "amount": str(amount) if amount else "0",
        "companyname": "ZwennPay",
        "shopnm": "ZwennPay"
    }
    
    return send_with_auto_recovery("/Displayqrcode", params, "QR code")

def send_payment_status_to_bhim_device(status, order_id, bank_rrn="", date=None):
    """Send payment status (success/cancel/fail) to BHIM device"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    params = {
        "orderid": str(order_id),
        "bankrrn": str(bank_rrn),
        "date": str(date)
    }
    
    # Choose endpoint based on status
    if status.lower() == "success":
        endpoint = "/DisplayQRCodeSucessStatus"
    elif status.lower() == "cancel":
        endpoint = "/DisplayQRCodeCancelStatus"
    elif status.lower() == "fail":
        endpoint = "/DisplayQRCodeFailStatus"
    else:
        print(f"❌ Invalid status: {status}")
        return False
    
    return send_with_auto_recovery(endpoint, params, f"payment status '{status}'")

def broadcast_qr_update(qr_data, amount=None):
    """Broadcast QR update to all connected SSE clients and BHIM device"""
    message = {
        "type": "qr_update",
        "qr_data": qr_data,
        "amount": amount,
        "timestamp": datetime.now().isoformat()
    }
    
    # Send to all connected SSE clients
    with sse_clients_lock:
        disconnected_clients = []
        for client_id, client in sse_clients.items():
            if client.connected:
                client.add_message(message)
            else:
                disconnected_clients.append(client_id)
        
        # Clean up disconnected clients
        for client_id in disconnected_clients:
            del sse_clients[client_id]
    
    print(f"📡 Broadcasted QR update to {len(sse_clients)} clients")
    
    # Also send to BHIM device
    send_qr_to_bhim_device(qr_data, amount)

def format_sse_message(data, event_type="message"):
    """Format data as Server-Sent Events message"""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

def send_heartbeat():
    """Send heartbeat to all connected clients"""
    heartbeat_msg = {
        "type": "heartbeat",
        "timestamp": datetime.now().isoformat()
    }
    
    with sse_clients_lock:
        for client in sse_clients.values():
            if client.connected:
                client.add_message(heartbeat_msg)

def cleanup_stale_clients():
    """Remove clients that haven't been active"""
    current_time = time.time()
    with sse_clients_lock:
        stale_clients = []
        for client_id, client in sse_clients.items():
            if current_time - client.last_heartbeat > 300:  # 5 minutes timeout
                stale_clients.append(client_id)
        
        for client_id in stale_clients:
            print(f"🧹 Cleaning up stale client: {client_id}")
            del sse_clients[client_id]

def get_current_qr_data():
    """Thread-safe getter for current QR data"""
    with qr_data_lock:
        return current_qr_data.copy()

# MQTT client setup with callbacks (for receiving messages only)
client = mqtt.Client()
client.username_pw_set(USER, PASSWORD)
client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect
client.connect(BROKER, PORT, 60)
client.loop_start()

def create_fresh_mqtt_client():
    """Create a fresh MQTT client for publishing only (no message receiving)"""
    fresh_client = mqtt.Client(clean_session=True)
    fresh_client.username_pw_set(USER, PASSWORD)
    # NO callbacks set - this client only publishes, never receives messages
    return fresh_client

def publish_with_fresh_connection(payload, timeout=10):
    """Publish MQTT message with fresh connection to avoid session issues"""
    fresh_client = None
    try:
        # Create fresh client (publish-only, no message receiving)
        fresh_client = create_fresh_mqtt_client()
        
        # Connect with timeout
        fresh_client.connect(BROKER, PORT, 60)
        
        # Use synchronous connection check instead of loop_start to avoid message receiving
        start_time = time.time()
        while not fresh_client.is_connected() and (time.time() - start_time) < timeout:
            fresh_client.loop(timeout=0.1)  # Process network events without starting background loop
        
        if not fresh_client.is_connected():
            print("❌ Fresh MQTT connection failed")
            return False
        
        # Publish message
        result = fresh_client.publish(TOPIC, payload)
        
        # Process the publish without starting background loop
        fresh_client.loop(timeout=0.5)
        
        print("✅ Published with fresh MQTT connection")
        return True
        
    except Exception as e:
        print(f"❌ Fresh MQTT publish error: {e}")
        return False
    finally:
        # Clean up fresh client
        if fresh_client:
            fresh_client.disconnect()

# Background thread for periodic cleanup
def background_cleanup():
    """Background thread to clean up stale clients"""
    while True:
        time.sleep(60)  # Run every minute
        cleanup_stale_clients()

cleanup_thread = threading.Thread(target=background_cleanup, daemon=True)
cleanup_thread.start()

@app.route("/publish_qr", methods=["POST"])
def publish_qr():
    data = request.json
    amount = data.get("amount")
    if amount is None:
        return jsonify({"error": "Amount not provided"}), 400

    # Store amount for QR data context
    with qr_data_lock:
        current_qr_data["amount"] = str(amount)

    # Generate QR from API
    payload = {
        "MerchantId": 57,
        "SetTransactionAmount": True,
        "TransactionAmount": str(amount),
        "SetConvenienceIndicatorTip": False,
        "ConvenienceIndicatorTip": 0,
        "SetConvenienceFeeFixed": False,
        "ConvenienceFeeFixed": 0,
        "SetConvenienceFeePercentage": False,
        "ConvenienceFeePercentage": 0,
    }

    try:
        response = requests.post(
            "https://api.zwennpay.com:9425/api/v1.0/Common/GetMerchantQR",
            headers={"accept": "text/plain", "Content-Type": "application/json"},
            json=payload,
            timeout=20
        )
        response.raise_for_status()
        qr_data = response.text.strip()
        
        # Create MQTT payload with QR data and amount
        mqtt_payload = {
            "qr_data": qr_data,
            "amount": str(amount),
            "timestamp": datetime.now().isoformat()
        }
        
        # Publish with fresh connection to avoid BHIM device restart issues
        publish_success = publish_with_fresh_connection(json.dumps(mqtt_payload))
        
        if not publish_success:
            print("⚠️ Fresh MQTT publish failed, trying persistent connection")
            # Fallback to persistent connection
            client.publish(TOPIC, json.dumps(mqtt_payload))
        
        return jsonify({"status": "success", "qr_data": qr_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/qr-stream")
def qr_stream():
    """Server-Sent Events endpoint for real-time QR updates"""
    def event_stream():
        # Generate unique client ID
        client_id = str(uuid.uuid4())
        
        # Create and register new SSE client
        client = SSEClient(client_id)
        with sse_clients_lock:
            sse_clients[client_id] = client
        
        print(f"🔗 New SSE client connected: {client_id}")
        
        try:
            # Send initial connection message
            yield format_sse_message({
                "type": "connected",
                "client_id": client_id,
                "message": "Connected to QR stream"
            })
            
            # Send current QR data if available
            current_data = get_current_qr_data()
            if current_data["qr_data"] is not None:
                yield format_sse_message({
                    "type": "qr_update",
                    "qr_data": current_data["qr_data"],
                    "amount": current_data["amount"],
                    "timestamp": current_data["timestamp"]
                })
            
            # Keep connection alive and send messages
            last_heartbeat = time.time()
            while client.connected:
                try:
                    # Update heartbeat
                    client.last_heartbeat = time.time()
                    
                    # Send any queued messages
                    messages = client.get_messages()
                    for message in messages:
                        yield format_sse_message(message)
                    
                    # Send heartbeat every 15 seconds (shorter for mobile)
                    current_time = time.time()
                    if current_time - last_heartbeat >= 15:
                        yield format_sse_message({
                            "type": "heartbeat",
                            "timestamp": datetime.now().isoformat()
                        })
                        last_heartbeat = current_time
                    
                    # Shorter sleep for better mobile responsiveness
                    time.sleep(0.5)
                    
                except GeneratorExit:
                    break
                except Exception as e:
                    print(f"❌ SSE stream error: {e}")
                    break
                
        except GeneratorExit:
            # Client disconnected
            print(f"🔌 SSE client disconnected: {client_id}")
            client.disconnect()
            with sse_clients_lock:
                if client_id in sse_clients:
                    del sse_clients[client_id]
    
    # Set up SSE response headers with mobile-friendly settings
    response = Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Cache-Control, Content-Type',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'X-Accel-Buffering': 'no'  # Disable nginx buffering
        }
    )
    
    return response

@app.route("/current_qr", methods=["GET"])
def get_current_qr():
    """Test endpoint to check current QR data state"""
    qr_data = get_current_qr_data()
    if qr_data["qr_data"] is None:
        return jsonify({"status": "no_qr", "message": "No QR code available"})
    
    return jsonify({
        "status": "success",
        "qr_data": qr_data["qr_data"],
        "amount": qr_data["amount"],
        "timestamp": qr_data["timestamp"]
    })

@app.route("/display")
def display():
    """Serve mobile QR display interface"""
    return render_template('qr_display.html')

@app.route("/qr-image")
def qr_image():
    """Generate QR code as PNG image (fallback for client-side generation)"""
    qr_data = request.args.get('data')
    if not qr_data:
        return jsonify({"error": "No QR data provided"}), 400
    
    try:
        import io
        from flask import send_file
        
        # Generate QR code using segno
        qr = segno.make(qr_data, error='M')
        buffer = io.BytesIO()
        qr.save(buffer, kind='png', scale=8, border=2)
        buffer.seek(0)
        
        return send_file(buffer, mimetype='image/png')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/test")
def test_page():
    """Serve test page for development"""
    with open('test_display.html', 'r') as f:
        return f.read()

@app.route("/test-js")
def test_javascript():
    """Serve JavaScript test page"""
    with open('test_javascript.html', 'r') as f:
        return f.read()

@app.route("/sse_status", methods=["GET"])
def sse_status():
    """Get status of SSE connections"""
    with sse_clients_lock:
        active_clients = len([c for c in sse_clients.values() if c.connected])
        return jsonify({
            "active_clients": active_clients,
            "total_clients": len(sse_clients),
            "client_ids": list(sse_clients.keys())
        })

@app.route("/mobile-test")
def mobile_test():
    """Simple test endpoint for mobile connectivity"""
    return jsonify({
        "status": "success",
        "message": "Mobile can reach Flask server!",
        "server_ip": request.environ.get('SERVER_NAME', 'unknown'),
        "client_ip": request.environ.get('REMOTE_ADDR', 'unknown'),
        "timestamp": datetime.now().isoformat()
    })

@app.route("/test-bhim", methods=["POST"])
def test_bhim_device():
    """Test connectivity and QR display on BHIM device"""
    data = request.json or {}
    test_qr = data.get("qr_data", "upi://pay?pa=test@paytm&pn=Test&am=100&cu=MUR")
    test_amount = data.get("amount", "100")
    
    success = send_qr_to_bhim_device(test_qr, test_amount)
    
    return jsonify({
        "status": "success" if success else "failed",
        "message": f"BHIM device test {'successful' if success else 'failed'}",
        "device_ip": BHIM_DEVICE_IP,
        "timestamp": datetime.now().isoformat()
    })

@app.route("/bhim-status", methods=["GET"])
def bhim_device_status():
    """Check BHIM device connectivity and status"""
    try:
        # Try a simple message endpoint to test connectivity
        response = requests.get(
            f"{BHIM_DEVICE_URL}/msg",
            params={"img": "", "title": "Connection Test"},
            timeout=5
        )
        
        if response.status_code == 200:
            return jsonify({
                "status": "online",
                "device_ip": BHIM_DEVICE_IP,
                "response": response.text,
                "timestamp": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "status": "error",
                "device_ip": BHIM_DEVICE_IP,
                "error": f"Device responded with status {response.status_code}",
                "timestamp": datetime.now().isoformat()
            })
            
    except requests.exceptions.ConnectionError:
        return jsonify({
            "status": "offline",
            "device_ip": BHIM_DEVICE_IP,
            "error": "Cannot connect to device",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "device_ip": BHIM_DEVICE_IP,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        })

@app.route("/bhim-welcome", methods=["POST"])
def bhim_welcome():
    """Send welcome message to BHIM device"""
    data = request.json or {}
    title = data.get("title", "Welcome to Artemis Hospital")
    img = data.get("img", "")
    
    success = send_welcome_to_bhim_device(title, img)
    
    return jsonify({
        "status": "success" if success else "failed",
        "message": f"Welcome message {'sent' if success else 'failed'}",
        "device_ip": BHIM_DEVICE_IP,
        "timestamp": datetime.now().isoformat()
    })

@app.route("/bhim-total", methods=["POST"])
def bhim_total():
    """Send total amount display to BHIM device"""
    data = request.json or {}
    total_amount = data.get("total_amount", 0)
    discount = data.get("discount", 0)
    tax = data.get("tax", 0)
    grand_total = data.get("grand_total")
    
    success = send_total_to_bhim_device(total_amount, discount, tax, grand_total)
    
    return jsonify({
        "status": "success" if success else "failed",
        "message": f"Total display {'sent' if success else 'failed'}",
        "device_ip": BHIM_DEVICE_IP,
        "timestamp": datetime.now().isoformat()
    })

@app.route("/bhim-payment-status", methods=["POST"])
def bhim_payment_status():
    """Send payment status to BHIM device"""
    data = request.json or {}
    status = data.get("status", "success")  # success, cancel, fail
    order_id = data.get("order_id", "")
    bank_rrn = data.get("bank_rrn", "")
    date = data.get("date")
    
    success = send_payment_status_to_bhim_device(status, order_id, bank_rrn, date)
    
    return jsonify({
        "status": "success" if success else "failed",
        "message": f"Payment status '{status}' {'sent' if success else 'failed'}",
        "device_ip": BHIM_DEVICE_IP,
        "timestamp": datetime.now().isoformat()
    })

if __name__ == "__main__":
    import socket
    
    # Get local IP address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "localhost"
    
    print("🚀 Starting QR Publisher API...")
    print(f"📱 Local Display URL: http://localhost:5001/display")
    print(f"🌐 Network Display URL: http://{local_ip}:5001/display")
    print(f"📡 SSE Stream: http://{local_ip}:5001/qr-stream")
    print("=" * 50)
    print(f"📲 Mobile URL: http://{local_ip}:5001/display")
    print(f"💳 BHIM Device: http://{BHIM_DEVICE_IP}")
    print("=" * 50)
    print("🔧 BHIM Device API Endpoints:")
    print(f"   - BHIM Status: GET http://{local_ip}:5001/bhim-status")
    print(f"   - Test BHIM: POST http://{local_ip}:5001/test-bhim")
    print(f"   - Welcome Message: POST http://{local_ip}:5001/bhim-welcome")
    print(f"   - Display Total: POST http://{local_ip}:5001/bhim-total")
    print(f"   - Payment Status: POST http://{local_ip}:5001/bhim-payment-status")
    print("=" * 50)
    print("🔧 Troubleshooting:")
    print("   - Ensure mobile and laptop are on same WiFi")
    print("   - Check Windows Firewall allows port 5001")
    print("   - Ensure BHIM device is accessible at 192.168.100.73")
    print("   - Try disabling Windows Firewall temporarily")
    print("=" * 50)
    
    app.run(host="0.0.0.0", port=5001, debug=True, threaded=True)
