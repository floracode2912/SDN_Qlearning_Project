import os
import time
from functools import partial
from mininet.topo import Topo
from mininet.node import Node, RemoteController, OVSKernelSwitch
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

# =======================================
# BUILD SDN TOPOLOGY
# =======================================
class SDNIoTTopo(Topo):
    def build(self):
        g1 = self.addSwitch("g1",  protocols='OpenFlow13')
        g2 = self.addSwitch("g2",  protocols='OpenFlow13')

        # Cloud server
        cloud = self.addHost("cloud", ip="10.0.100.2/24", defaultRoute="via 10.0.100.1")

        # Switches Access 
        s1 = self.addSwitch("s1",  protocols='OpenFlow13')
        s2 = self.addSwitch("s2",  protocols='OpenFlow13')
        s3 = self.addSwitch("s3",  protocols='OpenFlow13')
        s4 = self.addSwitch("s4",  protocols='OpenFlow13')

        # Links & IP Assignment
        bw_router = 10
        bw_host = 10

        # G1 <-> Subnets
        self.addLink(g1, s1, intfName1="g1-eth1", bw=bw_router)
        self.addLink(g1, s2, intfName1="g1-eth2", bw=bw_router)
        self.addLink(g1, s3, intfName1="g1-eth3", bw=bw_router)

        # G2 <-> Subnet
        self.addLink(g2, s4, intfName1="g2-eth1", bw=bw_router)

        # Backbone G1 <-> G2
        self.addLink(g1, g2,
                     intfName1="g1-eth10",
                     intfName2="g2-eth10",
                     bw=10)

        # G1 <-> Cloud
        self.addLink(g1, cloud, intfName1="g1-eth100", bw=bw_router)
        
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
    topo = SDNIoTTopo()
    
    switch_with_protocol = partial(OVSKernelSwitch, protocols='OpenFlow13')

    net = Mininet(topo=topo, controller= None , switch=switch_with_protocol, link=TCLink)
             
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)

    net.start()

    info("\n=== SDN NETWORK STARTED ===\n")
    info("[!] Warning: You MUST run a Ryu/ONOS Controller for connectivity.\n")
    info("    Example: ryu-manager iot_controller.py\n")
    
    info("Waiting for controller connection...\n")
    time.sleep(3)

    # --- START IOT SERVICES ---
    g1, cloud = net.get("g1", "cloud")
    
    info("\n=== STARTING IOT SIMULATION ===\n")
    
    # 1. Start Server
    info(f"[*] Starting Cloud Dashboard on {cloud.IP()}...\n")
    cloud.cmd("PYTHONIOENCODING=utf-8 python3 iot_server.py > server.log 2>&1 &")
    time.sleep(5) 

    # 2. Start Sensors
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
    info("SDN Simulation Running!\n")
    info("View Dashboard: http://10.0.100.2\n")
    info("------------------------------------------------\n")

    CLI(net)
    
    os.system("pkill -f iot_server.py")
    os.system("pkill -f iot_sensor.py")
    net.stop()

if __name__ == "__main__":
    setLogLevel("info")
    run()
