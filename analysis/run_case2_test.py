import os
import sys
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def main():
    # === Nếu không chạy bằng root, tự gọi lại với sudo ===
    if os.geteuid() != 0:
        print("⚙️  Đang tự khởi chạy lại với quyền sudo...")
        cmd = ['sudo', sys.executable] + sys.argv
        os.execvp('sudo', cmd)
        return

    # === Import topo sau khi có quyền root ===
    from mininet.net import Mininet
    from mininet.node import RemoteController
    from mininet.cli import CLI
    from mininet.log import setLogLevel, info
    from topology.iot_case2_topo import IoTCase2Topo

    setLogLevel('info')

    info("*** Khởi tạo mạng Mininet\n")
    topo = IoTCase2Topo()
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6653),
        autoSetMacs=True
    )

    info("*** Bắt đầu mạng\n")
    net.start()
    result = net.pingAll()
    print(f"\n📊 Kết quả pingAll: {result}% packet loss")
    CLI(net)
    net.stop()

if __name__ == "__main__":
    main()
