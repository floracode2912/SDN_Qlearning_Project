from mininet.topo import Topo

class IoTCase2Topo(Topo):
    def build(self):
        s1 = self.addSwitch('s1')

        for i in range(1, 6):
            h = self.addHost(f'h{i}', ip=f'10.0.0.{i}/24')
            self.addLink(h, s1)

        g1 = self.addHost('g1', ip='10.0.0.10/24')
        self.addLink(g1, s1)

        h6 = self.addHost('h6', ip='10.0.0.100/24')
        self.addLink(h6, s1)

topos = {'iot_case2': (lambda: IoTCase2Topo())}
