from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4, ether_types
from ryu.lib import hub
from ryu.topology import event
from ryu.topology.api import get_switch, get_link
import networkx as nx

class SmartController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SmartController, self).__init__(*args, **kwargs)
        self.topology_api_app = self
        self.net = nx.DiGraph() 
        self.datapaths = {}
        self.arp_table = {} 
        
        hub.spawn(self.topology_discovery)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        self.datapaths[datapath.id] = datapath

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.logger.info(f"--> [INIT] Switch connected: {datapath.id}")

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    def topology_discovery(self):
        while True:
            try:
                switch_list = get_switch(self.topology_api_app, None)
                switches = [switch.dp.id for switch in switch_list]
                self.net.add_nodes_from(switches)

                link_list = get_link(self.topology_api_app, None)
                links = [(link.src.dpid, link.dst.dpid, {'port': link.src.port_no})
                         for link in link_list]
                self.net.add_edges_from(links)
                
                if len(switches) > 0:
                    # self.logger.info(f"--- [TOPO] Nodes: {len(switches)} | Links: {len(links)} ---")
                    pass
            except Exception as e:
                pass
            hub.sleep(2)

    # CORE LOGIC
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        # --- LOGIC 1: ARP PROXY ---
        if eth.ethertype == ether_types.ETH_TYPE_ARP:
            arp_pkt = pkt.get_protocols(arp.arp)[0]
            
            # 1.1  IP -> MAC
            if arp_pkt.src_ip not in self.arp_table:
                self.arp_table[arp_pkt.src_ip] = src
                self.logger.info(f"  [ARP LEARN] Learned {arp_pkt.src_ip} is at {src}")

            # 1.2  Request
            if arp_pkt.opcode == arp.ARP_REQUEST:
                if arp_pkt.dst_ip in self.arp_table:
                    self.logger.info(f"  [ARP PROXY] ✅ Replying to {arp_pkt.src_ip}: {arp_pkt.dst_ip} is at {self.arp_table[arp_pkt.dst_ip]}")
                    self.send_arp_reply(datapath, in_port, src, arp_pkt.dst_ip, 
                                        self.arp_table[arp_pkt.dst_ip], arp_pkt.src_ip)
                    return
                else:
                    self.logger.info(f"  [ARP FLOOD] ⚠️ Don't know {arp_pkt.dst_ip}. Flooding...")
            
            # Flood
            data = None
            if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                data = msg.data
            out = parser.OFPActionOutput(ofproto.OFPP_FLOOD)
            out_packet = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                            in_port=in_port, actions=[out], data=data)
            datapath.send_msg(out_packet)
            return

        # --- LOGIC 2: IP ROUTING ---
        if eth.ethertype == ether_types.ETH_TYPE_IP:
            if src not in self.net:
                self.net.add_node(src)
                self.net.add_edge(dpid, src, port=in_port)
                self.net.add_edge(src, dpid)
            
            if dst in self.net:
                try:
                    path = nx.shortest_path(self.net, src, dst)
                    self.logger.info(f"  [PATH] 🛤️ Found path: {path}")

                    if dpid in path:
                        next_hop = path[path.index(dpid) + 1]
                        if next_hop in self.net[dpid]:
                            out_port = self.net[dpid][next_hop]['port']
                            
                            # Flow
                            self.logger.info(f"  [FLOW] ⚡ Installing on Switch {dpid}: Dst={dst} -> OutPort={out_port}")
                            
                            actions = [parser.OFPActionOutput(out_port)]
                            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_type=ether_types.ETH_TYPE_IP)
                            self.add_flow(datapath, 1, match, actions)
                            
                            data = None
                            if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                                data = msg.data
                            out_packet = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                                            in_port=in_port, actions=actions, data=data)
                            datapath.send_msg(out_packet)
                            return
                except Exception as e:
                    self.logger.info(f"  [ERROR] Path calculation failed: {e}")
                    pass 

        # Default Flood
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        out = parser.OFPActionOutput(ofproto.OFPP_FLOOD)
        out_packet = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                         in_port=in_port, actions=[out], data=data)
        datapath.send_msg(out_packet)

    def send_arp_reply(self, datapath, port, eth_dst, ip_src, mac_src, ip_dst):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_ARP,
                                           dst=eth_dst, src=mac_src))
        pkt.add_protocol(arp.arp(opcode=arp.ARP_REPLY,
                                 src_mac=mac_src, src_ip=ip_src,
                                 dst_mac=eth_dst, dst_ip=ip_dst))
        pkt.serialize()
        actions = [parser.OFPActionOutput(port)]
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions, data=pkt.data)
        datapath.send_msg(out)
