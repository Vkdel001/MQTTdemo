# Artemis Mauritius Hospital Billing System

A comprehensive hospital billing and payment system for Artemis Mauritius. The system consists of a React-based billing terminal for hospital staff and a mobile-optimized QR display interface for patient payments.

## Project Overview

This system enables staff to generate payment QR codes from a desktop/laptop interface, which are then instantly displayed on mobile devices for customer scanning. The system uses MQTT for real-time communication and Server-Sent Events (SSE) for live updates.

## Architecture

- **Frontend**: React TypeScript application (POS Terminal)
- **Backend**: Flask Python API server
- **Communication**: MQTT broker + Server-Sent Events
- **QR Generation**: ZwennPay API integration
- **Display**: Mobile-optimized HTML interface

## Prerequisites

- Python 3.7+
- Node.js 14+
- npm
- Internet connection (for MQTT broker and QR API)

## How to Run

### 1. Start the Backend (Flask Server)

Install Python dependencies:
```bash
pip install flask flask-cors requests segno paho-mqtt
```

Start the Flask server:
```bash
python publisherAPI.py
```

The server will start on port 5001 and display network information including the mobile URL.

### 2. Start the Frontend (React POS Terminal)

Navigate to the React application:
```bash
cd mqtt-qr-frontend
```

Install dependencies:
```bash
npm install
```

Start the development server:
```bash
npm start
```

The POS terminal opens at `http://localhost:3000`

### 3. Access the Applications

**For Staff (POS Terminal):**
- Open `http://localhost:3000` on your laptop
- Browse pharmacy products, add to cart, generate QR codes

**For Mobile Display:**
- Open `http://192.168.100.221:5001/display` on mobile browser
- QR codes will appear automatically when generated

### 4. Complete Workflow

1. **Staff:** Browse hospital services and add to patient bill on laptop
2. **Staff:** Click "Generate Payment QR" 
3. **Mobile:** QR code appears instantly on mobile display
4. **Patient:** Scans QR code from mobile screen
5. **System:** Shows "Waiting for payment..." for 12 seconds
6. **System:** Confirms "Payment received successfully!"
7. **Bill:** Automatically clears after payment confirmation

## Usage

### Staff Operation (Hospital Billing Terminal)
1. **Laptop:** Open `http://localhost:3000` (Artemis Hospital Billing System)
2. Browse hospital services by department (Consultation, Laboratory, Radiology, etc.)
3. Add services to patient bill with desired quantities
4. Review bill summary and total amount
5. Click "Generate Payment QR"
6. QR code appears instantly on mobile display

### Mobile Display Setup
1. Connect mobile device to same network as laptop
2. **Mobile:** Open `http://192.168.100.221:5001/display` (QR Display)
3. QR codes appear automatically when generated from POS terminal
4. Customer scans QR code from mobile screen

## Project Structure

```
├── publisherAPI.py              # Flask backend server
├── publisher.py                 # Standalone QR publisher
├── subscriber_display.py        # Tkinter display (legacy)
├── subscriber_old.py           # MQTT subscriber utility
├── templates/
│   └── qr_display.html         # Mobile QR display interface
├── static/
│   └── qrcode-simple.js        # QR code library
├── mqtt-qr-frontend/           # React POS terminal
│   ├── src/
│   │   ├── App.tsx             # Main React component
│   │   ├── PublisherForm.tsx   # POS terminal interface
│   │   └── PublisherForm.css   # Styling
│   ├── package.json            # React dependencies
│   └── tsconfig.json           # TypeScript configuration
├── test_display.html           # Development test page
├── test_javascript.html        # JavaScript test utilities
└── README.md
```

## Key Dependencies

### Python (Backend)
- `flask` - Web framework
- `flask-cors` - Cross-origin resource sharing
- `requests` - HTTP client for QR API
- `segno` - QR code generation
- `paho-mqtt` - MQTT client

### React (Frontend)
- `react` - UI framework
- `typescript` - Type safety
- `mqtt` - MQTT client library
- `qrcode.react` - QR code component

## Configuration

### MQTT Settings (publisherAPI.py)
```python
BROKER = "nodered-mqtt.bonrix.in"
PORT = 21883
USER = "nxon"
PASSWORD = "nxon1234"
TOPIC = "test1"
```

### ZwennPay API Configuration
- Merchant ID: 57
- Endpoint: `https://apiuat.zwennpay.com:9425/api/v1.0/Common/GetMerchantQR`

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/publish_qr` | POST | Generate and publish QR code |
| `/qr-stream` | GET | SSE stream for real-time updates |
| `/display` | GET | Mobile QR display interface |
| `/current_qr` | GET | Get current QR data state |
| `/qr-image` | GET | Generate QR as PNG image |
| `/sse_status` | GET | Check SSE connection status |
| `/mobile-test` | GET | Test mobile connectivity |

## Network Configuration

### Windows Firewall
Add firewall rule for port 5001:
```cmd
netsh advfirewall firewall add rule name="Flask QR Server" dir=in action=allow protocol=TCP localport=5001
```

### Router Issues
If mobile can't connect on WiFi, disable AP Isolation in router settings or use mobile hotspot as alternative.

## Development Scripts

### React Application
```bash
cd mqtt-qr-frontend
npm start          # Development server
npm run build      # Production build
npm test           # Run tests
```

### Python Backend
```bash
python publisherAPI.py     # Main Flask server
python publisher.py        # Standalone QR publisher
python subscriber_old.py   # MQTT subscriber test
```

## Troubleshooting

### Mobile Connection Issues
1. Verify same network connection
2. Check Windows Firewall settings
3. Test with mobile hotspot
4. Check router AP Isolation settings

### QR Display Problems
1. Monitor browser console for errors
2. Check SSE connection status (colored dot in display)
3. Verify MQTT broker connectivity
4. Test API endpoints manually

### React Development Issues
1. Ensure Node.js 14+ is installed
2. Clear npm cache: `npm cache clean --force`
3. Delete node_modules and reinstall: `rm -rf node_modules && npm install`

## Currency Configuration

The system uses Mauritian Rupees (MUR). To modify:

**React Frontend** (`PublisherForm.tsx`):
```tsx
<span className="currency-symbol">MUR</span>
```

**Mobile Display** (`qr_display.html`):
```javascript
amountDisplay.textContent = `MUR ${parseFloat(amount).toFixed(2)}`;
```

## Production Deployment

1. Build React application: `npm run build`
2. Configure Flask for production environment
3. Set up proper HTTPS certificates
4. Configure production MQTT broker
5. Update API endpoints for production

## Support

This system is developed for SMS PARIAZ Sports & Recreation Center, Mauritius.