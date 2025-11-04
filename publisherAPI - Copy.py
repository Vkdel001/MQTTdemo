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
        qr_data = msg.payload.decode()
        timestamp = datetime.now().isoformat()
        
        # Thread-safe update of current QR data
        with qr_data_lock:
            current_qr_data["qr_data"] = qr_data
            current_qr_data["timestamp"] = timestamp
            # Amount will be set when publishing
        
        print(f"📩 Received QR Data: {len(qr_data)} chars at {timestamp}")
        
        # Broadcast to SSE clients (will be implemented in later tasks)
        broadcast_qr_update(qr_data, current_qr_data.get("amount"))
        
    except Exception as e:
        print(f"❌ Error handling MQTT message: {e}")

def on_connect(client, userdata, flags, rc):
    """Handle MQTT connection"""
    if rc == 0:
        print("✅ Connected to MQTT broker (BHIM Device)")
        print(f"🔗 Broker: {BROKER}:{PORT}")
        print(f"�  User: {USER}")
        print(f"📡 Topic: {TOPIC}")
        client.subscribe(TOPIC)
        print(f"📡 Subscribed to topic '{TOPIC}'")
    else:
        print(f"❌ MQTT connection failed with code {rc}")
        print("🔧 Check BHIM device MQTT credentials")

def on_disconnect(client, userdata, rc):
    """Handle MQTT disconnection"""
    print(f"📡 Disconnected from MQTT broker (code: {rc})")
    if rc != 0:
        print("⚠️ Unexpected disconnection from BHIM device broker")

def on_publish(client, userdata, mid):
    """Handle MQTT publish confirmation"""
    print(f"✅ MQTT message published successfully (Message ID: {mid})")
    print("📱 QR data should now appear on BHIM device at 192.168.100.73")

def broadcast_qr_update(qr_data, amount=None):
    """Broadcast QR update to all connected SSE clients"""
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

# MQTT client setup (will be created per request like MQTTX)
def create_fresh_mqtt_connection():
    """Create fresh MQTT connection for each request (like MQTTX)"""
    print(f"🔄 Creating fresh MQTT connection to: {BROKER}:{PORT}")
    mqtt_client = mqtt.Client()
    mqtt_client.username_pw_set(USER, PASSWORD)
    return mqtt_client

def send_mqtt_message(qr_data, amount):
    """Send MQTT message using MQTTX pattern"""
    import time
    import random
    
    # Generate unique client ID (like MQTTX)
    client_id = f"artemis_{int(time.time())}_{random.randint(1000, 9999)}"
    print(f"🔄 Creating MQTT client: {client_id}")
    
    # Connection tracking
    connection_success = False
    publish_success = False
    
    try:
        # Create fresh client (like MQTTX createMqttClient)
        mqtt_client = mqtt.Client(client_id=client_id, clean_session=True)
        mqtt_client.username_pw_set(USER, PASSWORD)
        
        print(f"🔗 Connecting to: {BROKER}:{PORT}")
        
        # MQTTX pattern: on('connect') callback
        def on_connect(client, userdata, flags, rc):
            nonlocal connection_success, publish_success
            if rc == 0:
                print("✅ MQTT connected")
                connection_success = True
                
                # Publish immediately after connection (MQTTX pattern)
                print(f"📤 Publishing to topic: {TOPIC}")
                print(f"📊 Raw QR Data: {qr_data[:50]}...")
                
                # Try BHIM device expected format (based on API documentation)
                import base64
                qr_base64 = base64.b64encode(qr_data.encode()).decode()
                
                # Format message like BHIM API expects
                bhim_message = {
                    "qrcodebase64": qr_base64,
                    "upiurl": qr_data,
                    "amount": str(amount),
                    "companyname": "Artemis Mauritius",
                    "shopnm": "Hospital"
                }
                
                message_payload = json.dumps(bhim_message)
                
                print(f"📤 Publishing BHIM format to topic: {TOPIC}")
                print(f"📊 Broker: {BROKER}:{PORT}")
                print(f"📊 Message format: JSON with API parameters")
                print(f"📊 Payload sample: {message_payload[:100]}...")
                
                # Publish with callback (like MQTTX)
                result = client.publish(TOPIC, message_payload, qos=0)
                print(f"📤 Publish initiated (Message ID: {result.mid})")
            else:
                print(f"❌ Connection failed: {rc}")
        
        # MQTTX pattern: publish callback
        def on_publish(client, userdata, mid):
            nonlocal publish_success
            print(f"✅ Message published successfully (ID: {mid})")
            print(f"📡 Message sent to BHIM device at 192.168.100.73")
            print(f"📡 Topic: {TOPIC}")
            print(f"📡 Broker confirmed delivery")
            publish_success = True
            # Disconnect after successful publish (MQTTX pattern)
            client.disconnect()
        
        def on_disconnect(client, userdata, rc):
            print(f"🔌 Disconnected (code: {rc})")
        
        # Set callbacks (MQTTX pattern)
        mqtt_client.on_connect = on_connect
        mqtt_client.on_publish = on_publish
        mqtt_client.on_disconnect = on_disconnect
        
        # Connect and start loop
        mqtt_client.connect(BROKER, PORT, 60)
        mqtt_client.loop_start()
        
        # Wait for connection and publish (max 10 seconds)
        wait_time = 0
        while not publish_success and wait_time < 10:
            time.sleep(0.1)
            wait_time += 0.1
        
        # Clean shutdown
        mqtt_client.loop_stop()
        
        if publish_success:
            print("✅ QR sent to BHIM device successfully!")
            return True
        else:
            print("❌ Publish timeout or failed")
            return False
            
    except Exception as e:
        print(f"❌ MQTT error: {e}")
        return False

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
    try:
        print("🔄 Received QR generation request")
        data = request.json
        print(f"📊 Request data: {data}")
        
        amount = data.get("amount")
        if amount is None:
            print("❌ Amount not provided in request")
            return jsonify({"error": "Amount not provided"}), 400

        print(f"💰 Processing amount: MUR {amount}")

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

        print("🌐 Calling ZwennPay API...")
        response = requests.post(
            "https://apiuat.zwennpay.com:9425/api/v1.0/Common/GetMerchantQR",
            headers={"accept": "text/plain", "Content-Type": "application/json"},
            json=payload,
            timeout=15  # Reasonable timeout
        )
        
        print(f"📡 API Response Status: {response.status_code}")
        response.raise_for_status()
        qr_data = response.text.strip()
        print(f"✅ QR Data received: {len(qr_data)} characters")
        
        # Send QR to BHIM device via HTTP API (as per documentation)
        print("📤 Sending QR to BHIM device via HTTP API...")
        print(f"🎯 Target Device: 192.168.100.73")
        print(f"📊 QR Data: {qr_data[:50]}...")
        
        http_success = False
        
        try:
            import base64
            import time
            
            qr_base64 = base64.b64encode(qr_data.encode()).decode()
            
            # API #4: Display QR Code Screen (as per documentation)
            params = {
                'qrcodebase64': qr_base64,
                'upiurl': qr_data,
                'amount': amount,
                'companyname': 'Artemis Mauritius',
                'shopnm': 'Hospital'
            }
            
            # Try different API paths (test UI might use different endpoint)
            api_endpoints = [
                "http://192.168.100.73/Displayqrcode",           # Original
                "http://192.168.100.73/api/Displayqrcode",       # With /api
                "http://192.168.100.73/test/Displayqrcode",      # Test path
                "http://192.168.100.73/dynamic/Displayqrcode",   # Dynamic path
                "http://192.168.100.73/qr/display",              # Alternative
            ]
            print(f"🌐 Calling BHIM API: {bhim_url}")
            print(f"💰 Amount: MUR {amount}")
            
            # First check if device is ready
            print("🔍 Checking device status...")
            try:
                status_response = requests.get("http://192.168.100.73/", timeout=5)
                print(f"📊 Device status: {status_response.status_code}")
            except:
                print("⚠️ Device not responding to basic requests")
            
            # Retry logic for device initialization
            max_retries = 3
            retry_delay = 2  # seconds
            
            # Try each API endpoint once
            for endpoint_url in api_endpoints:
                try:
                    print(f"🔄 Trying endpoint: {endpoint_url}")
                    
                    # Completely fresh request (like test UI)
                    headers = {
                        'Connection': 'close',
                        'Cache-Control': 'no-cache',
                        'User-Agent': 'ArtemisHospital'
                    }
                    
                    bhim_response = requests.get(endpoint_url, params=params, headers=headers, timeout=5)
                    
                    if bhim_response.status_code == 200:
                        print("✅ QR successfully sent to BHIM device!")
                        print(f"📱 BHIM Response: {bhim_response.text}")
                        print(f"✅ Working endpoint: {endpoint_url}")
                        http_success = True
                        break
                    else:
                        print(f"❌ Status {bhim_response.status_code} from {endpoint_url}")
                        
                except Exception as e:
                    print(f"❌ Error with {endpoint_url}: {str(e)[:50]}...")
                    
            if not http_success:
                print("❌ All API endpoints failed")
                except requests.exceptions.ConnectionError:
                    print(f"🔌 Connection error - attempt {attempt + 1}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
            
            if not http_success:
                print("❌ All retry attempts failed - device may still be initializing")
                
        except Exception as e:
            print(f"❌ Error sending to BHIM device: {e}")
        
        if http_success:
            print("✅ QR sent successfully to BHIM device!")
        else:
            print("❌ Failed to send QR to BHIM device")
        
        # MQTT-only approach - no HTTP endpoints
        
        return jsonify({
            "status": "success", 
            "qr_data": qr_data,
            "amount": amount,
            "message": "QR code generated successfully"
        })
        
    except requests.exceptions.Timeout:
        error_msg = "QR API request timed out. Please try again."
        print(f"⏰ {error_msg}")
        return jsonify({"error": error_msg}), 408
        
    except requests.exceptions.ConnectionError:
        error_msg = "Unable to connect to QR API. Please check internet connection."
        print(f"🌐 {error_msg}")
        return jsonify({"error": error_msg}), 503
        
    except requests.exceptions.HTTPError as e:
        error_msg = f"QR API returned error: {e.response.status_code}"
        print(f"🚫 {error_msg}")
        return jsonify({"error": error_msg}), 502
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(f"❌ {error_msg}")
        return jsonify({"error": error_msg}), 500

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

@app.route("/health")
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "Artemis Hospital Billing System",
        "timestamp": datetime.now().isoformat(),
        "mqtt_connected": client.is_connected() if hasattr(client, 'is_connected') else "unknown"
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
    print("=" * 50)
    print("🔧 Troubleshooting:")
    print("   - Ensure mobile and laptop are on same WiFi")
    print("   - Check Windows Firewall allows port 5001")
    print("   - Try disabling Windows Firewall temporarily")
    print("=" * 50)
    
    app.run(host="0.0.0.0", port=5001, debug=True, threaded=True, use_reloader=False)
