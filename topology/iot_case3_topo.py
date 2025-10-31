from mininet.net import Mininet
from mininet.node import Node, RemoteController
from mininet.link import TCLink
from mininet.topo import Topo
from mininet.cli import CLI
import os

class LinuxRouter(Node):
    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        self.cmd('sysctl -w net.ipv4.ip_forward=1')
    def terminate(self):
        self.cmd('sysctl -w net.ipv4.ip_forward=0')
        super(LinuxRouter, self).terminate()

class SDNCase2Topo(Topo):
    def build(self):
        gw = self.addNode('gw', cls=LinuxRouter, ip='10.0.10.1/24')
        r1 = self.addNode('r1', cls=LinuxRouter, ip='10.0.10.2/24')
        r2 = self.addNode('r2', cls=LinuxRouter, ip='10.0.20.2/24')
        r3 = self.addNode('r3', cls=LinuxRouter, ip='10.0.30.2/24')
        cloud = self.addHost('cloud', ip='10.0.100.2/24', defaultRoute='via 10.0.100.1')

        s1, s2, s3, s4 = [self.addSwitch(s) for s in ('s1', 's2', 's3', 's4')]

        # hosts
        hosts_s1 = [self.addHost(f'h{i}', ip=f'10.0.1.{i}/24') for i in range(1, 4)]
        hosts_s2 = [self.addHost(f'h{i}', ip=f'10.0.2.{i}/24') for i in range(4, 6)]
        hosts_s3 = [self.addHost(f'h{i}', ip=f'10.0.3.{i}/24') for i in range(6, 8)]
        hosts_s4 = [self.addHost(f'h{i}', ip=f'10.0.4.{i}/24') for i in range(8, 11)]

        # Links
        self.addLink(gw, r1, intfName1='gw-eth1', params1={'ip':'10.0.10.1/24'})
        self.addLink(gw, r2, intfName1='gw-eth2', params1={'ip':'10.0.20.1/24'})
        self.addLink(gw, r3, intfName1='gw-eth3', params1={'ip':'10.0.30.1/24'})
        self.addLink(gw, cloud, intfName1='gw-eth4', params1={'ip':'10.0.100.1/24'})
        self.addLink(r1, s1)
        self.addLink(r2, s2)
        self.addLink(r2, s3)
        self.addLink(r3, s4)
        for h in hosts_s1: self.addLink(s1, h)
        for h in hosts_s2: self.addLink(s2, h)
        for h in hosts_s3: self.addLink(s3, h)
        for h in hosts_s4: self.addLink(s4, h)

def run():
    os.system('sudo mn -c')
    topo = SDNCase2Topo()
    net = Mininet(topo=topo, controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6653))
    net.start()
    CLI(net)
    net.stop()

if __name__ == '__main__':
    run()
