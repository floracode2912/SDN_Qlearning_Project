import os
import time
from functools import partial
from mininet.topo import Topo
from mininet.node import Node, RemoteController, OVSKernelSwitch
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

class SDNIoTTreeTopo(Topo):
    def build(self):
        g1 = self.addSwitch("g1", dpid="0000000000000100")
        g2 = self.addSwitch("g2", dpid="0000000000000200")
        g3 = self.addSwitch("g3", dpid="0000000000000300")

        # 2. Cloud server
        cloud = self.addHost("cloud", ip="10.0.100.2/24", defaultRoute="via 10.0.100.1")

        # 3. Switches
        s1 = self.addSwitch("s1", dpid="0000000000000001")
        s2 = self.addSwitch("s2", dpid="0000000000000002")
        s3 = self.addSwitch("s3", dpid="0000000000000003")
        s4 = self.addSwitch("s4", dpid="0000000000000004")

        bw_router = 10
        bw_host = 10

        # --- LINKS ---

        # G1 <-> Cloud
        self.addLink(g1, cloud, intfName1="g1-eth0", intfName2="cloud-eth0", 
                     bw=1, max_queue_size=10)

        # G3 <-> Cloud 
        self.addLink(g3, cloud, intfName1="g3-eth2", intfName2="cloud-eth1", bw=10)

        # G1 <-> S1
        self.addLink(g1, s1, intfName1="g1-eth1", bw=bw_router)
        # G1 <-> S2
        self.addLink(g1, s2, intfName1="g1-eth2", bw=bw_router)

        # G1 <-> G2 
        self.addLink(g1, g2, intfName1="g1-eth3", intfName2="g2-eth0", bw=50)

        # G1 <-> G3 
        self.addLink(g1, g3, intfName1="g1-eth4", intfName2="g3-eth0", bw=50)

        # G2 <-> S3
        self.addLink(g2, s3, intfName1="g2-eth1", bw=bw_router)

        # G3 <-> S4
        self.addLink(g3, s4, intfName1="g3-eth1", bw=bw_router)

        # --- HOSTS ---
        for i in range(1, 4): 
            self.addHost(f"h{i}", ip=f"10.0.1.{i}/24", defaultRoute="via 10.0.1.254")
            self.addLink(s1, f"h{i}", bw=bw_host)
        
        for i in range(4, 6): 
            self.addHost(f"h{i}", ip=f"10.0.2.{i}/24", defaultRoute="via 10.0.2.254")
            self.addLink(s2, f"h{i}", bw=bw_host)

        for i in range(6, 8): 
            self.addHost(f"h{i}", ip=f"10.0.3.{i}/24", defaultRoute="via 10.0.3.254")
            self.addLink(s3, f"h{i}", bw=bw_host)

        for i in range(8, 11): 
            self.addHost(f"h{i}", ip=f"10.0.4.{i}/24", defaultRoute="via 10.0.4.254")
            self.addLink(s4, f"h{i}", bw=bw_host)

def run():
    topo = SDNIoTTreeTopo()
    
    switch_with_protocol = partial(OVSKernelSwitch, protocols='OpenFlow13')
    
    net = Mininet(topo=topo, controller=None, switch=switch_with_protocol, link=TCLink)
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)

    net.start()

    cloud = net.get('cloud')
    cloud.cmd("ip addr add 10.0.200.2/24 dev cloud-eth1")
    cloud.cmd("ip link set cloud-eth1 up")

    info("\n=== SDN NETWORK STARTED ===\n")
    info("Waiting for controller...\n")
    time.sleep(3)

    cloud.cmd("ping -c 1 10.0.100.1")
    cloud.cmd("ping -c 1 10.0.200.1")

    # --- START IOT SERVICES ---
    info("\n=== STARTING IOT SIMULATION (CASE 2) ===\n")
    cloud.cmd("PYTHONIOENCODING=utf-8 python3 iot_server.py > server.log 2>&1 &")
    cloud.cmd("iperf -s -u -p 5001 &") 
    time.sleep(2) 

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
    info("   (M? xterm cloud -> firefox 10.0.100.2)\n")
    info("2. View logs: tail -f server.log\n")
    info("------------------------------------------------\n")

    info("\nRunning... CLI ready.\n")
    CLI(net)
    
    os.system("pkill -f iot_server.py")
    os.system("pkill -f iot_sensor.py")
    os.system("pkill -f iperf")
    net.stop()

if __name__ == "__main__":
    setLogLevel("info") 
    run()
