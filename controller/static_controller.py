from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4, lldp
from ryu.lib.packet import ether_types
from ryu.lib import hub
from ryu.lib.dpid import dpid_to_str, str_to_dpid
import networkx as nx
import time

class SmartSDNController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SmartSDNController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.ip_to_mac = {}
        self.ip_to_node = {}
        self.datapaths = {}
        self.network = nx.Graph()
        self.path_cache = {}
        self.flood_count = 0
        self.flow_count = 0
        self.log_file = open("/tmp/controller_log.txt", "w")
        hub.spawn(self._discovery)
        hub.spawn(self._log_stats)

    # === Periodic LLDP Discovery ===
    def _discovery(self):
        while True:
            self._send_lldp()
            hub.sleep(5)

    def _log_stats(self):
        while True:
            self.log_file.write(f"{time.time()} FLOODS={self.flood_count} FLOWS={self.flow_count}\n")
            self.log_file.flush()
            hub.sleep(10)

    def _send_lldp(self):
        for dp in list(self.datapaths.values()):
            parser = dp.ofproto_parser
            for port_no in list(dp.ports.keys()):
                if port_no > dp.ofproto.OFPP_MAX:
                    continue
                lldp_pkt = self._build_lldp(dp.id, port_no)
                actions = [parser.OFPActionOutput(port_no)]
                out = parser.OFPPacketOut(
                    datapath=dp, buffer_id=dp.ofproto.OFP_NO_BUFFER,
                    in_port=dp.ofproto.OFPP_CONTROLLER, actions=actions, data=lldp_pkt
                )
                dp.send_msg(out)

    def _build_lldp(self, dpid, port_no):
        chassis_id = lldp.ChassisID(subtype=lldp.ChassisID.SUB_LOCALLY_ASSIGNED,
                                    chassis_id=dpid_to_str(dpid).encode('ascii'))
        port_id = lldp.PortID(subtype=lldp.PortID.SUB_LOCALLY_ASSIGNED,
                              port_id=str(port_no).encode('ascii'))
        ttl = lldp.TTL(ttl=120)
        end = lldp.End()
        lldp_pkt = lldp.lldp([chassis_id, port_id, ttl, end])
        eth_pkt = ethernet.ethernet(dst=lldp.LLDP_MAC_NEAREST_BRIDGE,
                                    src='00:00:00:00:00:00',
                                    ethertype=ether_types.ETH_TYPE_LLDP)
        pkt = packet.Packet()
        pkt.add_protocol(eth_pkt)
        pkt.add_protocol(lldp_pkt)
        return pkt.serialize()

    def get_path(self, src_dpid, dst_dpid):
        if (src_dpid, dst_dpid) in self.path_cache:
            return self.path_cache[(src_dpid, dst_dpid)]
        try:
            path = nx.shortest_path(self.network, src_dpid, dst_dpid)
            self.path_cache[(src_dpid, dst_dpid)] = path
            return path
        except nx.NetworkXNoPath:
            return None

    def get_out_port(self, dpid, next_dpid):
        return self.network.edges[(dpid, next_dpid)]['src_port']

    # === Flow mặc định ===
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.datapaths[datapath.id] = datapath
        self.network.add_node(datapath.id)
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.logger.info(f"[Switch {datapath.id}] Flow mặc định đã được cài.")

    def add_flow(self, datapath, priority, match, actions, idle_timeout=60, hard_timeout=0):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst,
                                idle_timeout=idle_timeout, hard_timeout=hard_timeout)
        datapath.send_msg(mod)
        self.flow_count += 1

    # === Gói tin đến Controller ===
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            self._update_topology(pkt, datapath.id, in_port)
            return

        src = eth.src
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        pkt_arp = pkt.get_protocol(arp.arp)
        pkt_ip = pkt.get_protocol(ipv4.ipv4)

        if pkt_arp:
            self._handle_arp(datapath, pkt_arp, eth, in_port)
            return
        if pkt_ip:
            self._handle_ipv4(datapath, msg, pkt_ip, in_port)
            return

    # === LLDP Topology update ===
    def _update_topology(self, pkt, dst_dpid, dst_port):
        lldp_pkt = pkt.get_protocol(lldp.lldp)
        if not lldp_pkt:
            return
        chassis = next((tlv for tlv in lldp_pkt.tlvs if isinstance(tlv, lldp.ChassisID)), None)
        port = next((tlv for tlv in lldp_pkt.tlvs if isinstance(tlv, lldp.PortID)), None)
        if chassis and port:
            src_dpid = str_to_dpid(chassis.chassis_id)
            src_port = int(port.port_id)
            self.network.add_edge(src_dpid, dst_dpid, src_port=src_port, dst_port=dst_port)

    # === ARP Handler ===
    def _handle_arp(self, datapath, a, eth, in_port):
        src_ip = a.src_ip
        dst_ip = a.dst_ip
        self.ip_to_mac[src_ip] = eth.src
        self.ip_to_node[src_ip] = (datapath.id, in_port)
        if a.opcode == arp.ARP_REQUEST and dst_ip in self.ip_to_mac:
            self.reply_arp(datapath, eth, a, in_port)
        else:
            self._limited_flood(datapath, a, in_port)

    # === IPv4 Handler ===
    def _handle_ipv4(self, datapath, msg, pkt_ip, in_port):
        src_ip, dst_ip = pkt_ip.src, pkt_ip.dst
        self.ip_to_node[src_ip] = (datapath.id, in_port)
        if dst_ip in self.ip_to_node:
            out_dpid, out_port = self.ip_to_node[dst_ip]
            path = self.get_path(datapath.id, out_dpid)
            if path:
                for i in range(len(path) - 1):
                    curr_dp = self.datapaths[path[i]]
                    next_dp = path[i + 1]
                    outp = self.get_out_port(path[i], next_dp)
                    match = curr_dp.ofproto_parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=dst_ip)
                    actions = [curr_dp.ofproto_parser.OFPActionOutput(outp)]
                    self.add_flow(curr_dp, 10, match, actions)
                self._send_packet(datapath, msg, in_port, [datapath.ofproto_parser.OFPActionOutput(outp)])
            else:
                self._limited_flood(datapath, msg, in_port)
        else:
            self._limited_flood(datapath, msg, in_port)

    def _limited_flood(self, datapath, msg, in_port):
        self.flood_count += 1
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=msg.buffer_id,
                                  in_port=in_port,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)

    def _send_packet(self, datapath, msg, in_port, actions):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=msg.buffer_id,
                                  in_port=in_port,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)

    def reply_arp(self, datapath, eth, a, in_port):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        if a.dst_ip not in self.ip_to_mac:
            return
        target_mac = self.ip_to_mac[a.dst_ip]
        ether_reply = ethernet.ethernet(dst=eth.src, src=target_mac, ethertype=ether_types.ETH_TYPE_ARP)
        arp_reply = arp.arp(opcode=arp.ARP_REPLY,
                            src_mac=target_mac, src_ip=a.dst_ip,
                            dst_mac=eth.src, dst_ip=a.src_ip)
        pkt = packet.Packet()
        pkt.add_protocol(ether_reply)
        pkt.add_protocol(arp_reply)
        pkt.serialize()
        actions = [parser.OFPActionOutput(in_port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=pkt.data)
        datapath.send_msg(out)
