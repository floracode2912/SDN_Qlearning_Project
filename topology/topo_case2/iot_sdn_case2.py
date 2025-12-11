import os
import time
from functools import partial
from mininet.topo import Topo
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

class SDNIoTTreeTopo(Topo):
    def build(self):
        # 1. Switches (Core & Aggregation)
        # G1: Core Router
        g1 = self.addSwitch("g1", dpid="0000000000000100")
        # G2: Aggregation cho Zone 3
        g2 = self.addSwitch("g2", dpid="0000000000000200")
        # G3: Aggregation cho Zone 4 + Backup Link
        g3 = self.addSwitch("g3", dpid="0000000000000300")

        # Access Switches
        s1 = self.addSwitch("s1", dpid="0000000000000001")
        s2 = self.addSwitch("s2", dpid="0000000000000002")
        s3 = self.addSwitch("s3", dpid="0000000000000003")
        s4 = self.addSwitch("s4", dpid="0000000000000004")

        # 2. Cloud Server (Multi-homing)
        cloud = self.addHost("cloud", ip="10.0.100.2/24", 
                             mac="00:00:00:00:00:FF",
                             defaultRoute="via 10.0.100.1")

        bw_router = 10
        bw_host = 10

        # --- LINKS ---
        
        self.addLink(g1, cloud, port1=1, port2=0, 
                     bw=1.5, max_queue_size=100) 
        # Port 2: Ra S1 (Zone 1)
        self.addLink(g1, s1, port1=2, bw=bw_router)
        # Port 3: Ra S2 (Zone 2)
        self.addLink(g1, s2, port1=3, bw=bw_router)
        # Port 4: Ra G2 (Zone 3)
        self.addLink(g1, g2, port1=4, port2=1, bw=50)
        # Port 5: Ra G3 (Zone 4 + Backup)
        self.addLink(g1, g3, port1=5, port2=1, bw=50)

        self.addLink(g2, s3, port1=2, bw=bw_router)

        self.addLink(g3, s4, port1=2, bw=bw_router)
        # Port 3: Backup ra Cloud
        self.addLink(g3, cloud, port1=3, port2=1, bw=10)

# --- HOSTS & ACCESS LINKS  ---
        # Zone 1 (10.0.1.x) -> S1
        for i in range(1, 4): 
            mac_addr = '00:00:00:00:00:%02x' % i
            self.addHost(f"h{i}", ip=f"10.0.1.{i}/24", mac=mac_addr, defaultRoute="via 10.0.1.254")
            self.addLink(s1, f"h{i}", bw=bw_host)
        
        # Zone 2 (10.0.2.x) -> S2
        for i in range(4, 6): 
            mac_addr = '00:00:00:00:00:%02x' % i
            self.addHost(f"h{i}", ip=f"10.0.2.{i}/24", mac=mac_addr, defaultRoute="via 10.0.2.254")
            self.addLink(s2, f"h{i}", bw=bw_host)

        # Zone 3 (10.0.3.x) -> S3
        for i in range(6, 8): 
            mac_addr = '00:00:00:00:00:%02x' % i
            self.addHost(f"h{i}", ip=f"10.0.3.{i}/24", mac=mac_addr, defaultRoute="via 10.0.3.254")
            self.addLink(s3, f"h{i}", bw=bw_host)

        # Zone 4 (10.0.4.x) -> S4
        for i in range(8, 11): 
            mac_addr = '00:00:00:00:00:%02x' % i
            self.addHost(f"h{i}", ip=f"10.0.4.{i}/24", mac=mac_addr, defaultRoute="via 10.0.4.254")
            self.addLink(s4, f"h{i}", bw=bw_host)

def run():
    topo = SDNIoTTreeTopo()
    switch_with_protocol = partial(OVSKernelSwitch, protocols='OpenFlow13')
    net = Mininet(topo=topo, controller=None, switch=switch_with_protocol, link=TCLink)
    
    info("[*] Connecting to Remote Controller...\n")
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)

    net.start()
    
    cloud = net.get('cloud')
    info("[*] Disabling rp_filter on Cloud...\n")

    cloud.cmd("ip addr add 10.0.200.2/24 dev cloud-eth1")
    cloud.cmd("ip link set cloud-eth1 up")
    cloud.cmd("ifconfig cloud-eth1 hw ether 00:00:00:00:00:FF")
    
    cloud.cmd("sysctl -w net.ipv4.conf.all.rp_filter=0")
    cloud.cmd("sysctl -w net.ipv4.conf.default.rp_filter=0")
    cloud.cmd("sysctl -w net.ipv4.conf.cloud-eth0.rp_filter=0")
    cloud.cmd("sysctl -w net.ipv4.conf.cloud-eth1.rp_filter=0")
    
    cloud.cmd("ip route add 10.0.0.0/16 via 10.0.100.1")

    info("\n=== SDN L3 TOPOLOGY STARTED ===\n")
    time.sleep(2)

    # Start Services
    info("[*] Starting Services...\n")
    cloud.cmd("PYTHONIOENCODING=utf-8 python3 iot_server.py > server.log 2>&1 &")
    cloud.cmd("iperf -s -u -p 5001 &") 
    
    sensors = {'h1': 'temp', 'h2': 'humid', 'h3': 'motion', 'h4': 'temp', 'h10': 'humid'}
    for h, t in sensors.items():
        node = net.get(h)
        node.cmd(f"python3 iot_sensor.py {h} {t} &")
        info(f" -> {h} started sending {t}\n")

    CLI(net)
    
    os.system("pkill -f iot_server.py")
    os.system("pkill -f iot_sensor.py")
    os.system("pkill -f iperf")
    net.stop()

if __name__ == "__main__":
    setLogLevel("info") 
    run()
