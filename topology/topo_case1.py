import os
import time
from mininet.topo import Topo
from mininet.node import Node, OVSController
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

# =======================================
# LINUX ROUTER CLASS
# =======================================
class LinuxRouter(Node):
    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        self.cmd("sysctl -w net.ipv4.ip_forward=1")

    def terminate(self):
        self.cmd("sysctl -w net.ipv4.ip_forward=0")
        super(LinuxRouter, self).terminate()

# =======================================
# BUILD TOPOLOGY 
# =======================================
class IoTStaticTopo(Topo):
    def build(self):
        # Routers = Gateways 
        g1 = self.addNode("g1", cls=LinuxRouter, ip=None)
        g2 = self.addNode("g2", cls=LinuxRouter, ip=None)

        # Cloud server
        cloud = self.addHost("cloud", ip="10.0.100.2/24", defaultRoute="via 10.0.100.1")

        # Switches
        s1 = self.addSwitch("s1")
        s2 = self.addSwitch("s2")
        s3 = self.addSwitch("s3")
        s4 = self.addSwitch("s4")

        # Links & IP Assignment
        bw_router = 10
        bw_host = 10

        # G1 <-> Subnets
        self.addLink(g1, s1, intfName1="g1-eth1", params1={"ip": "10.0.1.254/24"}, bw=bw_router)
        self.addLink(g1, s2, intfName1="g1-eth2", params1={"ip": "10.0.2.254/24"}, bw=bw_router)
        self.addLink(g1, s3, intfName1="g1-eth3", params1={"ip": "10.0.3.254/24"}, bw=bw_router)

        # G2 <-> Subnet
        self.addLink(g2, s4, intfName1="g2-eth1", params1={"ip": "10.0.4.254/24"}, bw=bw_router)

        # Backbone G1 <-> G2
        self.addLink(g1, g2,
                     intfName1="g1-eth10", params1={"ip": "10.0.10.1/24"},
                     intfName2="g2-eth10", params2={"ip": "10.0.10.2/24"},
                     bw=10)

        # G1 <-> Cloud
        self.addLink(g1, cloud, intfName1="g1-eth100",
                     params1={"ip": "10.0.100.1/24"}, bw=bw_router)

        # Hosts
        # S1 Hosts
        for i in range(1, 4):
            self.addHost(f"h{i}", ip=f"10.0.1.{i}/24", defaultRoute="via 10.0.1.254")
            self.addLink(s1, f"h{i}", bw=bw_host)
        
        # S2 Hosts
        for i in range(4, 6):
            self.addHost(f"h{i}", ip=f"10.0.2.{i}/24", defaultRoute="via 10.0.2.254")
            self.addLink(s2, f"h{i}", bw=bw_host)
            
        # S3 Hosts
        for i in range(6, 8):
            self.addHost(f"h{i}", ip=f"10.0.3.{i}/24", defaultRoute="via 10.0.3.254")
            self.addLink(s3, f"h{i}", bw=bw_host)
            
        # S4 Hosts
        for i in range(8, 11):
            self.addHost(f"h{i}", ip=f"10.0.4.{i}/24", defaultRoute="via 10.0.4.254")
            self.addLink(s4, f"h{i}", bw=bw_host)

# =======================================
# MAIN RUN
# =======================================
def run():
    topo = IoTStaticTopo()
    net = Mininet(topo=topo, controller=OVSController, link=TCLink)
    net.start()

    g1, g2, cloud = net.get("g1", "g2", "cloud")

    # Bật IP Forwarding
    g1.cmd("sysctl -w net.ipv4.ip_forward=1")
    g2.cmd("sysctl -w net.ipv4.ip_forward=1")

    info("\n=== CONFIGURING STATIC ROUTES ===\n")
    
    g1.cmd("ip route add 10.0.4.0/24 via 10.0.10.2")
    g2.cmd("ip route add default via 10.0.10.1")
    cloud.cmd("ip route add 10.0.0.0/16 via 10.0.100.1")

    info("Routing configured. Waiting for switches...\n")
    time.sleep(2)

    # --- START IOT SERVICES ---
    info("\n=== STARTING IOT SIMULATION ===\n")
    info(f"[*] Starting Cloud Dashboard on {cloud.IP()}...\n")
    cloud.cmd("PYTHONIOENCODING=utf-8 python3 iot_server.py > server.log 2>&1 &")
    time.sleep(2) 

    # Start Sensors
    sensors = {
        'h1': 'temp', 'h2': 'humid', 'h3': 'motion', 
        'h4': 'temp', 'h5': 'motion',                
        'h6': 'humid', 'h7': 'temp',                 
        'h8': 'motion', 'h9': 'temp', 'h10': 'humid' 
    }

    info("[*] Starting Sensors...\n")
    for hostname, stype in sensors.items():
        h = net.get(hostname)
        h.cmd(f"python3 iot_sensor.py {hostname} {stype} &")
        info(f" -> {hostname} started ({stype})\n")

    info("\n------------------------------------------------\n")
    info("Simulation Running!\n")
    info("1. Web Dashboard: http://10.0.100.2\n")
    info("   (Mở xterm cloud -> firefox 10.0.100.2)\n")
    info("2. View logs: tail -f server.log\n")
    info("------------------------------------------------\n")

    CLI(net)
    
    os.system("pkill -f iot_server.py")
    os.system("pkill -f iot_sensor.py")
    net.stop()

if __name__ == "__main__":
    setLogLevel("info")
    os.system("mn -c") 
    run()
