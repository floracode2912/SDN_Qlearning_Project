from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.link import TCLink
from mininet.topo import Topo
from mininet.cli import CLI
from mininet.log import setLogLevel, info
import os, time


class IoTCase2Topo(Topo):
    """
    Case 2: Mô hình SDN không cần sudo.
    Ryu controller điều khiển toàn bộ switch.
    """

    def build(self):
        info("\n*** Tạo Gateway và Cloud\n")
        gw = self.addHost('gw', ip='10.0.10.1/24')
        cloud = self.addHost('cloud', ip='10.0.100.2/24')

        info("*** Tạo các switch SDN\n")
        s1, s2, s3, s4 = [self.addSwitch(f's{i}') for i in range(1, 5)]

        info("*** Tạo các host IoT\n")
        hosts_s1 = [self.addHost(f'h{i}', ip=f'10.0.1.{i}/24') for i in range(1, 4)]
        hosts_s2 = [self.addHost(f'h{i}', ip=f'10.0.2.{i}/24') for i in range(4, 6)]
        hosts_s3 = [self.addHost(f'h{i}', ip=f'10.0.3.{i}/24') for i in range(6, 8)]
        hosts_s4 = [self.addHost(f'h{i}', ip=f'10.0.4.{i}/24') for i in range(8, 11)]

        info("*** Tạo liên kết\n")
        self.addLink(gw, s1, bw=10)
        self.addLink(s1, s2, bw=10)
        self.addLink(s2, s3, bw=10)
        self.addLink(s3, s4, bw=10)
        self.addLink(s4, cloud, bw=10)

        for h in hosts_s1: self.addLink(s1, h)
        for h in hosts_s2: self.addLink(s2, h)
        for h in hosts_s3: self.addLink(s3, h)
        for h in hosts_s4: self.addLink(s4, h)


def run():
    info("\n*** Khởi tạo mạng SDN (User Mode)...\n")

    topo = IoTCase2Topo()

    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6653),
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=True
    )

    net.start()
    info("\n✅ Mạng SDN (user) đã khởi động thành công!\n")

    info("\n*** Kiểm tra kết nối sơ bộ:\n")
    net.pingAll()

    info("\n*** CLI sẵn sàng.\n")
    CLI(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    run()
