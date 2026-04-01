# LoadFlow

**Intelligent Load Balancer Simulator**

LoadFlow is an interactive, enterprise-grade load balancing simulator designed for learning, demonstration, and exploring traffic distribution algorithms in real-time. Built with a stunning dark-themed dashboard, it allows you to visualize how requests are routed across an infrastructure.

---

## 🚀 Features

- **Real-Time Dashboard**: Monitor server health, CPU load, active connections, and response times as traffic flows through your virtual infrastructure.
- **Algorithm Comparison**: Switch live between algorithmic routing strategies:
  - **Round Robin**: Distributes requests sequentially.
  - **Least Connections**: Sends traffic to the server currently handling the fewest active requests.
  - **Weighted**: Distributes traffic based on pre-assigned server capacities.
- **Dynamic Scaling**: Add or remove servers on the fly and watch the algorithms instantly adapt to the new infrastructure.
- **Live Traffic Terminal**: A real-time matrix-style console that streams every request as it routes, color-coded by status and latency.
- **Comprehensive History**: Full audit logs with pagination, response time charts, and CSV export capabilities.

---

## 🛠️ Tech Stack

- **Backend**: Python / Flask
- **Frontend**: Vanilla HTML / CSS / JavaScript
- **Database**: SQLite (In-Memory / persisted logging)
- **Charts**: Chart.js for real-time data visualization

---

## 🚦 Getting Started

Starting the simulator is incredibly fast as it runs locally on your machine.

### Windows Users
Simply double-click:
```
START_SERVER.bat
```

### Mac/Linux Users
Start the Flask application directly:
```bash
python app.py
```

### Accessing the Simulator
Once running, open your browser and navigate to the landing page:
```
http://127.0.0.1:5000
```
*(Note: port may automatically adjust to 5001 or another if 5000 is occupied).*

---

## 🔧 Troubleshooting

If you encounter an "Unable to Connect" issue:
1. Ensure no other application is blocking port `5000`.
2. Check your terminal output. If Flask failed to bind, try running `python app.py` instead of the batch file to see explicit error messages.
3. If the server is stuck, kill the background Python process:
   - **Windows:** `taskkill /F /IM python.exe` *(Warning: This kills all Python processes)*.

## 📁 Project Structure

```
AWS/
├── app.py                    # Main Flask application logic & API endpoints
├── database.db               # Local SQLite database for history logging
├── START_SERVER.bat          # Easy-start script for Windows
├── templates/                # Jinja2 Layouts
│   ├── index.html            # Core metrics dashboard
│   ├── servers.html          # Dynamic server management grid
│   ├── compare.html          # Algorithm benchmarking UI
│   ├── history.html          # Request audit logs
│   ├── landing.html          # Public facing simulator portal
│   └── base.html             # Global site layout & navigation
└── static/
    └── css/style.css         # Global dark theme aesthetic
```
