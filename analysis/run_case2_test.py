import sys, os, time, subprocess, signal
from datetime import datetime
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import setLogLevel

# === Import topology ===
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from topology.iot_case2_topo import IoTCase2Topo

# === Cấu hình log ===
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "case2_results.txt")
os.makedirs(LOG_DIR, exist_ok=True)

RYU_PATH = "/home/npt/ryu/.venv/bin/ryu-manager"
RYU_APP = "/home/npt/SDN_Qlearning_Project/controller/simple_controller.py"
RYU_PORT = 6653

# ======================== HÀM HỖ TRỢ ============================

def log(msg):
    """Ghi log ra file và terminal"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def start_controller():
    """Khởi động Ryu controller"""
    log(f"[INFO] Đang khởi động Ryu controller: {RYU_APP}")
    process = subprocess.Popen(
        [RYU_PATH, RYU_APP],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid
    )
    # Chờ controller lên
    for i in range(15):
        time.sleep(1)
        result = os.system(f"nc -z 127.0.0.1 {RYU_PORT} >/dev/null 2>&1")
        if result == 0:
            log(f"[OK] Ryu controller đã sẵn sàng trên cổng {RYU_PORT}!")
            return process
        log(f"[INFO] Chờ Ryu khởi động... ({i+1}/15)")
    log("[FATAL] Không thể khởi động Ryu controller.")
    return None

def ensure_controller_alive(proc):
    """Kiểm tra controller còn sống không"""
    if proc.poll() is not None:
        log("[WARN] Ryu controller bị crash — khởi động lại!")
        return start_controller()
    return proc

def stop_controller(proc):
    """Tắt Ryu controller"""
    if proc and proc.poll() is None:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        log("[INFO] Đã tắt Ryu controller.")

# ======================== CHẠY CASE 2 ============================

def run_case2_test():
    setLogLevel('info')
    os.system("mn -c >/dev/null 2>&1")
    log("===============================================")
    log("[INFO] Bắt đầu chạy Case 2 - Kiểm thử IoT Topology")
    log("===============================================")

    controller_proc = start_controller()
    if not controller_proc:
        log("[FATAL] Không thể tiếp tục vì Ryu controller không khởi động được.")
        return

    # === Khởi tạo Mininet ===
    net = Mininet(
        topo=IoTCase2Topo(),
        switch=OVSSwitch,
        controller=lambda name: RemoteController(name, ip='127.0.0.1', port=RYU_PORT),
        autoSetMacs=True
    )

    try:
        net.start()
        log("[OK] Topology khởi tạo thành công!")
        time.sleep(8)

        h1, h6, s1 = net.get('h1', 'h6', 's1')

        # Đảm bảo controller còn sống
        controller_proc = ensure_controller_alive(controller_proc)

        # === PING TEST ===
        log("[TEST] Kiểm tra kết nối ping giữa h1 và h6...")
        h1.cmd("ping -c 2 10.0.0.100 > /dev/null")
        time.sleep(2)
        ping_loss = net.ping([h1, h6])
        log(f"[RESULT] Tỉ lệ mất gói ping = {ping_loss:.2f}%")

        # === IPERF TEST (UDP) ===
        log("[TEST] Đang đo băng thông UDP bằng iperf (3s)...")
        try:
            bw_result = net.iperf((h1, h6), l4Type='UDP', seconds=3)
            log(f"[RESULT] Băng thông trung bình giữa h1-h6: {bw_result}")
        except Exception as e:
            log(f"[ERROR] Không thể đo băng thông: {e}")

        # === ROUTING + FLOW ===
        log("[INFO] Bảng định tuyến của h1:")
        log(h1.cmd("route -n"))

        log("[INFO] Bảng định tuyến của h6:")
        log(h6.cmd("route -n"))

        log("[INFO] Luồng OVS (flow table) của s1:")
        log(s1.cmd("ovs-ofctl dump-flows s1"))

    except Exception as e:
        log(f"[FATAL] Lỗi trong quá trình chạy Case 2: {e}")

    finally:
        log("[INFO] Dừng mạng Mininet và dọn dẹp...")
        try:
            net.stop()
        except Exception:
            pass
        stop_controller(controller_proc)
        log("[DONE] Test Case 2 hoàn tất!\n\n")

# ======================== MAIN ============================

if __name__ == "__main__":
    run_case2_test()
