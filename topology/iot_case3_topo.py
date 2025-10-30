from mininet.topo import Topo
from mininet.node import Node

class LinuxRouter(Node):
    "Node đóng vai trò Router, bật IP forwarding"
    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        self.cmd('sysctl -w net.ipv4.ip_forward=1')
    def terminate(self):
        self.cmd('sysctl -w net.ipv4.ip_forward=0')
        super(LinuxRouter, self).terminate()

class IoTCase3Topo(Topo):
    """
    Case 3: IoT topology mở rộng có Router trung gian.
    Gateway <-> Router <-> Switch <-> Hosts
    """
    def build(self):
        # Gateway, Router, Switch
        gateway = self.addHost('g1', ip='10.0.0.1/24')
        router = self.addNode('r1', cls=LinuxRouter, ip='10.0.0.254/24')
        switch = self.addSwitch('s1')

        # IoT Hosts
        hosts = []
        for i in range(1, 7):
            host = self.addHost(f'h{i}', ip=f'10.0.0.{i+10}/24')
            hosts.append(host)

        # Liên kết
        self.addLink(gateway, router)
        self.addLink(router, switch)
        for h in hosts:
            self.addLink(switch, h)

topos = {'iot_case3': (lambda: IoTCase3Topo())}
