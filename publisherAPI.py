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
PORT = 21883
USER = "nxon"
PASSWORD = "nxon1234"
TOPIC = "test1"

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
        print("✅ Connected to MQTT broker")
        client.subscribe(TOPIC)
        print(f"📡 Subscribed to topic '{TOPIC}'")
    else:
        print(f"❌ MQTT connection failed with code {rc}")

def on_disconnect(client, userdata, rc):
    """Handle MQTT disconnection"""
    print(f"📡 Disconnected from MQTT broker (code: {rc})")

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

# MQTT client setup with callbacks
client = mqtt.Client()
client.username_pw_set(USER, PASSWORD)
client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect
client.connect(BROKER, PORT, 60)
client.loop_start()

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
        
        # Publish to MQTT (this will trigger our on_message callback)
        print("📤 Publishing to MQTT...")
        client.publish(TOPIC, qr_data)
        print("✅ MQTT publish successful")
        
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
