import sys, os, time, subprocess, signal
from datetime import datetime
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.log import setLogLevel

# === Import topology ===
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from topology.iot_case3_topo import IoTCase3Topo

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def is_controller_alive():
    """Kiểm tra controller có đang chạy không"""
    result = subprocess.run(["pgrep", "-f", "ryu-manager"], stdout=subprocess.PIPE)
    return result.returncode == 0

def start_controller():
    controller_path = "/home/npt/SDN_Qlearning_Project/controller/qlearning_controller.py"
    if not os.path.exists(controller_path):
        log(f"[FATAL] Không tìm thấy file controller tại {controller_path}")
        sys.exit(1)
    log(f"[INFO] Khởi động Q-Learning Controller: {controller_path}")
    RYU_PATH = "/home/npt/ryu/.venv/bin/ryu-manager"

    proc = subprocess.Popen(
    [RYU_PATH, controller_path],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)

    for i in range(15):
        if is_controller_alive():
            log("[OK] Controller sẵn sàng!")
            return proc
        time.sleep(1)
    log("[FATAL] Controller không khởi động được sau 15s!")
    sys.exit(1)

def stop_controller(proc):
    """Dừng controller an toàn"""
    try:
        if proc and proc.poll() is None:
            proc.terminate()
            time.sleep(1)
            if proc.poll() is None:
                proc.kill()
        log("[INFO] Đã tắt Ryu controller.")
    except Exception as e:
        log(f"[WARN] Lỗi khi dừng controller: {e}")

def run_case3_test():
    setLogLevel('info')
    os.system("mn -c >/dev/null 2>&1")

    log("===============================================")
    log("[CASE 3] Kiểm thử IoT Topology với SDN + Q-learning")
    log("===============================================")

    controller_proc = start_controller()

    net = None
    try:
        net = Mininet(
            topo=IoTCase3Topo(),
            switch=OVSSwitch,
            controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6653),
            autoSetMacs=True
        )

        net.start()
        time.sleep(5)
        h1, h6 = net.get('h1'), net.get('h6')

        log("[TEST] Ping giữa h1 và h6...")
        loss = net.ping([h1, h6])
        log(f"[RESULT] Ping loss = {loss:.2f}%")

        if loss < 100:
            log("[TEST] Đo băng thông UDP (3s)...")
            try:
                result = net.iperf((h1, h6), l4Type='UDP', seconds=3)
                log(f"[RESULT] UDP Throughput: {result}")
            except Exception as e:
                log(f"[WARN] Không thể đo băng thông: {e}")
        else:
            log("[WARN] Ping thất bại hoàn toàn — bỏ qua iperf.")

        # === Flow Table debug ===
        s1 = net.get('s1')
        log("[INFO] Flow Table tại s1:")
        log(s1.cmd("ovs-ofctl dump-flows s1"))

    except KeyboardInterrupt:
        log("[STOP] Dừng thủ công bởi người dùng.")
    except Exception as e:
        log(f"[FATAL] Lỗi trong quá trình chạy: {e}")
    finally:
        if net:
            try:
                net.stop()
            except Exception as e:
                log(f"[WARN] Lỗi khi dừng Mininet: {e}")
        stop_controller(controller_proc)
        log("[DONE] Case 3 hoàn tất!")

if __name__ == "__main__":
    run_case3_test()
