import sys, os, time, subprocess, signal
from datetime import datetime
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import setLogLevel

# === Import topology ===
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from topology.iot_case2_topo import IoTCase2Topo

# === Cấu hình môi trường ===
RYU_PATH = "/home/npt/ryu/.venv/bin/ryu-manager"
RYU_APP = "/home/npt/SDN_Qlearning_Project/controller/simple_controller.py"
RYU_PORT = 6653

# ===============================================================

def log(msg):
    """In log ra màn hình với timestamp"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def start_controller():
    """Khởi động Ryu controller trong nền"""
    log(f"[INFO] Khởi động Ryu controller: {RYU_APP}")
    proc = subprocess.Popen(
        [RYU_PATH, RYU_APP],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid
    )

    # Chờ controller khởi động
    for i in range(10):
        time.sleep(1)
        if os.system(f"nc -z 127.0.0.1 {RYU_PORT} >/dev/null 2>&1") == 0:
            log(f"[OK] Controller đã sẵn sàng (port {RYU_PORT})")
            return proc
    log("[ERROR] Controller không phản hồi.")
    return None

def ensure_controller_alive(proc):
    """Nếu controller chết thì khởi động lại"""
    if proc.poll() is not None:
        log("[WARN] Controller bị crash — tự động khởi động lại.")
        return start_controller()
    return proc

def stop_controller(proc):
    """Dừng Ryu controller"""
    if proc and proc.poll() is None:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        log("[INFO] Đã dừng Ryu controller.")

# ===============================================================

def run_case2_test():
    """
    Case 2: IoT topology kiểm thử cơ bản (gateway + switch + hosts)
    Có thể import lại từ Case 3 để tái sử dụng.
    """
    setLogLevel('info')
    os.system("mn -c >/dev/null 2>&1")

    log("===============================================")
    log("[CASE 2] Khởi động kiểm thử IoT Topology cơ bản")
    log("===============================================")

    # Khởi động controller
    controller_proc = start_controller()
    if not controller_proc:
        log("[FATAL] Không khởi động được controller. Dừng tiến trình.")
        return None

    # Khởi tạo mạng
    net = Mininet(
        topo=IoTCase2Topo(),
        switch=OVSSwitch,
        controller=lambda name: RemoteController(name, ip='127.0.0.1', port=RYU_PORT),
        autoSetMacs=True
    )

    try:
        net.start()
        log("[OK] Topology khởi tạo thành công.")
        time.sleep(5)

        # Lấy node
        h1, h6, s1 = net.get('h1', 'h6', 's1')

        # Đảm bảo controller còn sống
        controller_proc = ensure_controller_alive(controller_proc)

        # --- PING TEST ---
        log("[TEST] Ping h1 <-> h6 ...")
        h1.cmd("ping -c 2 10.0.0.100 > /dev/null")
        ping_loss = net.ping([h1, h6])
        log(f"[RESULT] Ping loss = {ping_loss:.2f}%")

        # --- IPERF TEST (UDP để giảm treo) ---
        log("[TEST] Đo băng thông UDP (3s)...")
        try:
            bw_result = net.iperf((h1, h6), l4Type='UDP', seconds=3)
            log(f"[RESULT] Băng thông trung bình: {bw_result}")
        except Exception as e:
            log(f"[WARN] Không thể đo băng thông: {e}")

        # --- ROUTING + FLOW TABLE ---
        log("[INFO] Routing table h1:")
        print(h1.cmd("route -n"))

        log("[INFO] Routing table h6:")
        print(h6.cmd("route -n"))

        log("[INFO] Flow table s1:")
        print(s1.cmd("ovs-ofctl dump-flows s1"))

    except Exception as e:
        log(f"[FATAL] Lỗi khi chạy Case 2: {e}")

    finally:
        log("[CLEANUP] Dừng mạng và controller...")
        try:
            net.stop()
        except Exception:
            pass
        stop_controller(controller_proc)
        log("[DONE] Case 2 hoàn tất.\n")

    return True

# ===============================================================

if __name__ == "__main__":
    run_case2_test()
