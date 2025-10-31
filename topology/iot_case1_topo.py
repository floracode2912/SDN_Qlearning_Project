from mininet.net import Mininet
from mininet.node import Node, OVSController
from mininet.link import TCLink
from mininet.topo import Topo
from mininet.cli import CLI
from mininet.log import setLogLevel, info
import os

# =======================================
# Define a Linux Router Node
# =======================================
class LinuxRouter(Node):
    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        self.cmd('sysctl -w net.ipv4.ip_forward=1')

    def terminate(self):
        self.cmd('sysctl -w net.ipv4.ip_forward=0')
        super(LinuxRouter, self).terminate()

# =======================================
# Define the Topology
# =======================================
class StaticRoutingTopo(Topo):
    def build(self):

        # Routers and gateway
        gw = self.addNode('gw', cls=LinuxRouter, ip='10.0.10.1/24')
        r1 = self.addNode('r1', cls=LinuxRouter, ip='10.0.10.2/24')
        r2 = self.addNode('r2', cls=LinuxRouter, ip='10.0.20.2/24')
        r3 = self.addNode('r3', cls=LinuxRouter, ip='10.0.30.2/24')

        # Cloud host
        cloud = self.addHost('cloud', ip='10.0.100.2/24', defaultRoute='via 10.0.100.1')

        # Switches
        s1, s2, s3, s4 = [self.addSwitch(s) for s in ('s1', 's2', 's3', 's4')]

        # Hosts
        hosts_s1 = [self.addHost(f'h{i}', ip=f'10.0.1.{i}/24', defaultRoute='via 10.0.1.254') for i in range(1, 4)]
        hosts_s2 = [self.addHost(f'h{i}', ip=f'10.0.2.{i}/24', defaultRoute='via 10.0.2.1') for i in range(4, 6)]
        hosts_s3 = [self.addHost(f'h{i}', ip=f'10.0.3.{i}/24', defaultRoute='via 10.0.3.1') for i in range(6, 8)]
        hosts_s4 = [self.addHost(f'h{i}', ip=f'10.0.4.{i}/24', defaultRoute='via 10.0.4.1') for i in range(8, 11)]

        # Gateway <-> Routers
        self.addLink(gw, r1, intfName1='gw-eth1', params1={'ip': '10.0.10.1/24'}) 
        self.addLink(gw, r2, intfName1='gw-eth2', params1={'ip': '10.0.20.1/24'}) 
        self.addLink(gw, r3, intfName1='gw-eth3', params1={'ip': '10.0.30.1/24'}) 
        
        # Routers <-> Switches
        self.addLink(r1, s1, intfName1='r1-eth1', params1={'ip': '10.0.1.254/24'})
        self.addLink(r2, s2, intfName1='r2-eth1', params1={'ip': '10.0.2.1/24'})
        self.addLink(r2, s3, intfName1='r2-eth2', params1={'ip': '10.0.3.1/24'})
        self.addLink(r3, s4, intfName1='r3-eth1', params1={'ip': '10.0.4.1/24'})

        # Gateway <-> Cloud
        self.addLink(gw, cloud, intfName1='gw-eth4', params1={'ip': '10.0.100.1/24'})

        # Switch <-> Hosts
        for h in hosts_s1: self.addLink(s1, h)
        for h in hosts_s2: self.addLink(s2, h)
        for h in hosts_s3: self.addLink(s3, h)
        for h in hosts_s4: self.addLink(s4, h)


# =======================================
# Configure Static Routes
# =======================================
def run():
    topo = StaticRoutingTopo()
    net = Mininet(topo=topo, controller=OVSController, link=TCLink)
    net.start()

    gw, r1, r2, r3 = net.get('gw', 'r1', 'r2', 'r3')

    info("\n*** Configuring static routes...\n")

    # ----------------------------
    # Gateway
    # ----------------------------
    gw.cmd('ip route add 10.0.1.0/24 via 10.0.10.2')
    gw.cmd('ip route add 10.0.2.0/24 via 10.0.20.2')
    gw.cmd('ip route add 10.0.3.0/24 via 10.0.20.2')
    gw.cmd('ip route add 10.0.4.0/24 via 10.0.30.2')
    gw.cmd('ip route add default via 10.0.100.2')

    # ----------------------------
    # Router 1 (connects subnet 10.0.1.0/24)
    # ----------------------------
    r1.cmd('ip route add default via 10.0.10.1')  # to GW
    r1.cmd('ip route add 10.0.2.0/24 via 10.0.10.1')
    r1.cmd('ip route add 10.0.3.0/24 via 10.0.10.1')
    r1.cmd('ip route add 10.0.4.0/24 via 10.0.10.1')
    r1.cmd('ip route add 10.0.100.0/24 via 10.0.10.1')

    # ----------------------------
    # Router 2 (connects subnets 10.0.2.0 and 10.0.3.0)
    # ----------------------------
    r2.cmd('ip route add default via 10.0.20.1')  # to GW
    r2.cmd('ip route add 10.0.0.0/24 via 10.0.20.1')
    r2.cmd('ip route add 10.0.4.0/24 via 10.0.20.1')
    r2.cmd('ip route add 10.0.100.0/24 via 10.0.20.1')

    # ----------------------------
    # Router 3 (connects subnet 10.0.4.0/24)
    # ----------------------------
    r3.cmd('ip route add default via 10.0.30.1')  # to GW
    r3.cmd('ip route add 10.0.0.0/24 via 10.0.30.1')
    r3.cmd('ip route add 10.0.2.0/24 via 10.0.30.1')
    r3.cmd('ip route add 10.0.3.0/24 via 10.0.30.1')
    r3.cmd('ip route add 10.0.100.0/24 via 10.0.30.1')  

    info("\n*** All routes configured successfully!\n")
    CLI(net)
    net.stop()


# =======================================
# Main
# =======================================
if __name__ == '__main__':
    setLogLevel('info')
    os.system('sudo mn -c')
    run()