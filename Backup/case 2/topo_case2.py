import os
import time
from functools import partial
from mininet.topo import Topo
from mininet.node import Node, RemoteController, OVSKernelSwitch
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

# ==========================================
# 1. CLASS TOPOLOGY: MẠNG IOT - SDN (SINGLE NETWORK)
# ==========================================
class SDNIoTFlatTopo(Topo):
    def build(self):
        # --- SWITCHES (SDN) ---
        g1 = self.addSwitch("g1", dpid="0000000000000100")
        g2 = self.addSwitch("g2", dpid="0000000000000200")
        g3 = self.addSwitch("g3", dpid="0000000000000300")
        s1 = self.addSwitch("s1", dpid="0000000000000001")
        s2 = self.addSwitch("s2", dpid="0000000000000002")
        s3 = self.addSwitch("s3", dpid="0000000000000003")
        s4 = self.addSwitch("s4", dpid="0000000000000004")

        cloud = self.addHost("cloud", ip="10.0.0.254/24")
      
        bw_backbone = 50   
        bw_uplink = 1.5    
        bw_access = 10     

        # --- LINKS ---

        self.addLink(g1, cloud, intfName1="g1-eth100", intfName2="cloud-eth0", 
                     bw=bw_uplink, max_queue_size=100)  
        self.addLink(g3, cloud, intfName1="g3-eth100", intfName2="cloud-eth1", 
                     bw=bw_backbone)
        self.addLink(g1, g2, bw=bw_backbone) 
        self.addLink(g1, g3, bw=bw_backbone) 
        self.addLink(g1, s1, bw=bw_access)
        self.addLink(g1, s2, bw=bw_access)
        self.addLink(g2, s3, bw=bw_access)
        self.addLink(g3, s4, bw=bw_access)

        # --- HOSTS (SENSORS) ---
        # Zone 1 -> S1
        for i in range(1, 4): 
            self.addHost(f"h{i}", ip=f"10.0.0.{i}/24")
            self.addLink(s1, f"h{i}", bw=bw_access)   
        # Zone 2 -> S2
        for i in range(4, 6): 
            self.addHost(f"h{i}", ip=f"10.0.0.{i}/24")
            self.addLink(s2, f"h{i}", bw=bw_access)
        # Zone 3 -> S3
        for i in range(6, 8): 
            self.addHost(f"h{i}", ip=f"10.0.0.{i}/24")
            self.addLink(s3, f"h{i}", bw=bw_access)
        # Zone 4 -> S4
        for i in range(8, 11): 
            self.addHost(f"h{i}", ip=f"10.0.0.{i}/24")
            self.addLink(s4, f"h{i}", bw=bw_access)
# ==========================================
# 2. MAIN FUNCTION
# ==========================================
def run():
    topo = SDNIoTFlatTopo()
    switch_with_protocol = partial(OVSKernelSwitch, protocols='OpenFlow13')   
    net = Mininet(topo=topo, 
                  controller=None, 
                  switch=switch_with_protocol, 
                  link=TCLink)
     
    info("[*] Connecting to Remote Controller...\n")
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)

    net.start()
    info("\n=== SDN IOT NETWORK STARTED (FLAT IP: 10.0.0.x/24) ===\n")
    time.sleep(2) 


    cloud = net.get('cloud')
    cloud.cmd("ip addr add 10.0.0.253/24 dev cloud-eth1") 
    cloud.cmd("ip link set cloud-eth1 up")
    info("[*] Starting Background Services...\n")
    cloud.cmd("PYTHONIOENCODING=utf-8 python3 iot_server.py > server.log 2>&1 &")
    cloud.cmd("iperf -s -u -p 5001 &") 
    

    sensors = {'h2': 'temp', 'h3': 'motion', 'h4': 'humid'}
    for h, t in sensors.items():
        node = net.get(h)

        node.cmd(f"python3 iot_sensor.py {h} {t} &")
        info(f" -> {h} started sending {t}\n")

    info("\n------------------------------------------------\n")
    info("Network Ready!\n")
    info("Cloud Main IP: 10.0.0.254 (via G1)\n")
    info("Cloud Backup IP: 10.0.0.253 (via G3)\n")
    info("All Hosts: 10.0.0.1 -> 10.0.0.10\n")
    info("------------------------------------------------\n")

    CLI(net)
    
    info("[*] Stopping network...\n")
    os.system("pkill -f iot_server.py")
    os.system("pkill -f iot_sensor.py")
    os.system("pkill -f iperf")
    net.stop()

if __name__ == "__main__":
    setLogLevel("info") 
    run()
