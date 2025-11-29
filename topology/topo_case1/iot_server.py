import http.server
import socketserver
import json
import time

PORT = 80
DATA_STORE = []

class IoTRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            # Giao diện Dashboard (HTML + CSS + JS)
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>IoT System Dashboard</title>
                <style>
                    body { font-family: sans-serif; background: #f4f6f9; padding: 20px; }
                    .header { background: #343a40; color: white; padding: 15px; text-align: center; border-radius: 5px; }
                    .container { display: flex; flex-wrap: wrap; justify-content: center; margin-top: 20px; }
                    .card { background: white; width: 300px; margin: 10px; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
                    .card h3 { margin-top: 0; color: #007bff; border-bottom: 2px solid #eee; padding-bottom: 10px; }
                    .value { font-size: 2em; font-weight: bold; color: #28a745; text-align: center; }
                    .alert { color: #dc3545; animation: blink 1s infinite; }
                    @keyframes blink { 50% { opacity: 0.5; } }
                    table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 0.9em; }
                    th, td { padding: 8px; border-bottom: 1px solid #ddd; text-align: left; }
                </style>
                <script>
                    function fetchData() {
                        fetch('/api/data')
                            .then(response => response.json())
                            .then(data => {
                                updateTable(data);
                                updateStats(data);
                            });
                    }
                    
                    function updateTable(data) {
                        let rows = "";
                        // Lấy 10 bản ghi mới nhất
                        data.slice().reverse().slice(0, 10).forEach(item => {
                            let status = item.alert ? "<b style='color:red'>WARNING</b>" : "<span style='color:green'>OK</span>";
                            rows += `<tr><td>${item.time}</td><td>${item.id}</td><td>${item.type}</td><td>${item.value}</td><td>${status}</td></tr>`;
                        });
                        document.getElementById("log-table").innerHTML = rows;
                    }

                    function updateStats(data) {
                        document.getElementById("total-packets").innerText = data.length;
                    }

                    setInterval(fetchData, 2000); // Tự động cập nhật mỗi 2 giây
                </script>
            </head>
            <body onload="fetchData()">
                <div class="header">
                    <h1>☁️ IoT Cloud Monitor Center</h1>
                </div>
                
                <div class="container">
                    <div class="card">
                        <h3>System Status</h3>
                        <p>Total Packets Received: <span id="total-packets" class="value">0</span></p>
                        <p>Server IP: <b>10.0.100.2</b></p>
                    </div>
                    <div class="card" style="width: 600px">
                        <h3>📋 Live Data Log</h3>
                        <table>
                            <thead><tr><th>Time</th><th>Device</th><th>Type</th><th>Value</th><th>Status</th></tr></thead>
                            <tbody id="log-table"></tbody>
                        </table>
                    </div>
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode('utf-8'))
            
        elif self.path == '/api/data':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(DATA_STORE).encode('utf-8'))
            
        else:
            self.send_error(404)

    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            # Xử lý dữ liệu
            data['time'] = time.strftime("%H:%M:%S")
            data['alert'] = False
            
            # Logic phân tích đơn giản
            if data['type'] == 'temp' and float(data['value']) > 80:
                data['alert'] = True # Cảnh báo cháy
            if data['type'] == 'motion' and int(data['value']) == 1:
                data['alert'] = True # Cảnh báo đột nhập

            DATA_STORE.append(data)
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        except:
            self.send_response(400)
            self.end_headers()

print(f"🚀 Cloud Server started at 10.0.100.2:{PORT}")
httpd = socketserver.TCPServer(("", PORT), IoTRequestHandler)
httpd.serve_forever()
