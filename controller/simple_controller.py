# -*- coding: utf-8 -*-
import sys
import time
import ipaddress
import networkx as nx
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, arp, ipv4, lldp
from ryu.lib import hub
from ryu.lib.dpid import dpid_to_str, str_to_dpid

# Ensure output encoding is UTF-8 to prevent crashes
sys.stdout.reconfigure(encoding='utf-8')

class UniversalRouter(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(UniversalRouter, self).__init__(*args, **kwargs)
        
        # Initialize variables
        self.datapaths = {} 
        self.mac_to_port = {}        # {dpid: {mac: port}}
        self.mac_to_dpid = {}        # {mac: dpid} - Global MAC map
        self.ip_to_mac = {}          # {ip: mac}
        self.network = nx.Graph()    # Topology Graph
        
        # ONE Virtual Gateway MAC for ALL subnets (Simplifies Routing Logic)
        self.GW_MAC = '00:00:00:00:00:FE'
        
        # List of Gateway IPs (Must match your Topology)
        # S1, S2, S3, S4 Gateways + Cloud Gateways + Backbone IPs
        self.GW_IPS = [
            '10.0.1.254', '10.0.2.254', '10.0.3.254', '10.0.4.254',
            '10.0.100.1', '10.0.200.1',
            '10.0.10.1', '10.0.10.2',
            '10.0.20.1', '10.0.20.2'
        ]
        
        # Start monitoring thread
        self.monitor_thread = hub.spawn(self._monitor)
        # Start discovery thread
        self.discovery_thread = hub.spawn(self._discovery_loop)
        
        print("\n" + "="*60)
        print("  CUSTOM IOT SDN CONTROLLER (SINGLE GW MAC)")
        print("  - Topology: Tree (G1 Root, G2/G3 Branch)")
        print(f"  - Virtual Gateway MAC: {self.GW_MAC}")
        print("="*60 + "\n")

    # --- MONITORING LOOP ---
    def _monitor(self):
        hub.sleep(2)
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(5)

    def _request_stats(self, datapath):
        parser = datapath.ofproto_parser
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        body = ev.msg.body
        for stat in sorted([flow for flow in body if flow.priority == 1],
                           key=lambda flow: (flow.packet_count), reverse=True):
            ip_src = stat.match.get('ipv4_src', 'N/A')
            ip_dst = stat.match.get('ipv4_dst', 'N/A')
            packet_count = stat.packet_count
            if packet_count > 0:
                print(f"Flow: {ip_src} -> {ip_dst} | Pkts: {packet_count}")

    # --- TOPOLOGY DISCOVERY (LLDP) ---
    def _discovery_loop(self):
        while True:
            for dp in list(self.datapaths.values()):
                for port in dp.ports.keys():
                    if port <= dp.ofproto.OFPP_MAX:
                        self._send_lldp(dp, port)
            hub.sleep(3) # Scan every 3s

    def _send_lldp(self, datapath, port):
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(port)]
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_LLDP,
                                           src='00:00:00:00:00:00', dst=lldp.LLDP_MAC_NEAREST_BRIDGE))
        chassis_id = lldp.ChassisID(subtype=lldp.ChassisID.SUB_LOCALLY_ASSIGNED,
                                    chassis_id=dpid_to_str(datapath.id).encode('ascii'))
        port_id = lldp.PortID(subtype=lldp.PortID.SUB_LOCALLY_ASSIGNED,
                              port_id=str(port).encode('ascii'))
        pkt.add_protocol(lldp.lldp([chassis_id, port_id, lldp.TTL(ttl=120), lldp.End()]))
        pkt.serialize()
        datapath.send_msg(parser.OFPPacketOut(datapath=datapath, buffer_id=datapath.ofproto.OFP_NO_BUFFER,
                                              in_port=datapath.ofproto.OFPP_CONTROLLER, actions=actions, data=pkt.data))

    # --- SWITCH CONNECTION ---
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id:
                self.datapaths[datapath.id] = datapath
                self.network.add_node(datapath.id)
                print(f" >> Switch {datapath.id:016x} Connected!")
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id and datapath.id in self.datapaths:
                del self.datapaths[datapath.id]
                self.network.remove_node(datapath.id)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(datapath.ofproto.OFPP_CONTROLLER, datapath.ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(datapath.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority, match=match, instructions=inst)
        datapath.send_msg(mod)

    # --- PACKET PROCESSING ---
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        
        if not eth: return
        if eth.ethertype == ether_types.ETH_TYPE_LLDP: 
            self._handle_lldp(datapath, in_port, pkt)
            return

        src_mac = eth.src
        dst_mac = eth.dst

        # 1. Global MAC Learning
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src_mac] = in_port
        self.mac_to_dpid[src_mac] = dpid 

        # 2. ARP Processing
        if eth.ethertype == ether_types.ETH_TYPE_ARP:
            self._handle_arp(datapath, in_port, eth, pkt.get_protocol(arp.arp), msg)
            return

        # 3. IPv4 Processing
        if eth.ethertype == ether_types.ETH_TYPE_IP:
            self._handle_ipv4(datapath, msg, pkt.get_protocol(ipv4.ipv4), in_port, eth)
            return

    # --- HANDLERS ---
    def _handle_lldp(self, datapath, in_port, pkt):
        try:
            lldp_pkt = pkt.get_protocol(lldp.lldp)
            chassis = lldp_pkt.tlvs[0].chassis_id.decode('ascii')
            port = lldp_pkt.tlvs[1].port_id.decode('ascii')
            src_dpid = str_to_dpid(chassis)
            src_port = int(port)
            if src_dpid != datapath.id:
                self.network.add_edge(src_dpid, datapath.id, src_port=src_port, dst_port=in_port)
                self.network.add_edge(datapath.id, src_dpid, src_port=in_port, dst_port=src_port)
        except: pass

    def _handle_arp(self, datapath, in_port, eth, arp_pkt, msg):
        src_ip = arp_pkt.src_ip
        dst_ip = arp_pkt.dst_ip
        self.ip_to_mac[src_ip] = eth.src

        if arp_pkt.opcode == arp.ARP_REQUEST:
            # Always reply with GW_MAC for any Gateway IP query
            if dst_ip in self.GW_IPS:
                self.send_arp_reply(datapath, in_port, self.GW_MAC, dst_ip, eth.src, src_ip)
            # Reply with real MAC for known hosts
            elif dst_ip in self.ip_to_mac:
                self.send_arp_reply(datapath, in_port, self.ip_to_mac[dst_ip], dst_ip, eth.src, src_ip)
            else:
                self.flood_packet(msg)
        elif arp_pkt.opcode == arp.ARP_REPLY:
            self.flood_packet(msg)

    def _handle_ipv4(self, datapath, msg, ip_pkt, in_port, eth):
        dst_ip = ip_pkt.dst
        src_ip = ip_pkt.src
        
        # Determine Routing vs Switching
        is_routing = (eth.dst == self.GW_MAC)

        # Target MAC
        final_dst_mac = eth.dst
        if is_routing:
            if dst_ip in self.ip_to_mac:
                final_dst_mac = self.ip_to_mac[dst_ip]
            else:
                self.send_arp_request_flood(datapath, dst_ip)
                return

        # Find Path
        if final_dst_mac not in self.mac_to_dpid:
            self.flood_packet(msg)
            return
        
        dst_dpid = self.mac_to_dpid[final_dst_mac]
        
        # If dst is on same switch
        if datapath.id == dst_dpid:
            out_port = self.mac_to_port[datapath.id][final_dst_mac]
        else:
            try:
                path = nx.shortest_path(self.network, datapath.id, dst_dpid)
                next_hop = path[1]
                out_port = self.network[datapath.id][next_hop]['src_port']
            except:
                self.flood_packet(msg)
                return

        actions = []
        if is_routing:
            actions.append(datapath.ofproto_parser.OFPActionSetField(eth_src=self.GW_MAC))
            actions.append(datapath.ofproto_parser.OFPActionSetField(eth_dst=final_dst_mac))
            actions.append(datapath.ofproto_parser.OFPActionDecNwTtl())
        
        actions.append(datapath.ofproto_parser.OFPActionOutput(out_port))
        
        match = datapath.ofproto_parser.OFPMatch(in_port=in_port, eth_dst=eth.dst, eth_type=0x0800, ipv4_src=src_ip, ipv4_dst=dst_ip)
        self.add_flow(datapath, 1, match, actions)
        self._packet_out(datapath, msg, in_port, actions)

    # --- HELPERS ---
    def flood_packet(self, msg):
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        self._packet_out(datapath, msg, msg.match['in_port'], actions)

    def send_arp_reply(self, datapath, port, src_mac, src_ip, dst_mac, dst_ip):
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_ARP, dst=dst_mac, src=src_mac))
        pkt.add_protocol(arp.arp(opcode=arp.ARP_REPLY, src_mac=src_mac, src_ip=src_ip, dst_mac=dst_mac, dst_ip=dst_ip))
        pkt.serialize()
        actions = [datapath.ofproto_parser.OFPActionOutput(port)]
        self._packet_out(datapath, None, datapath.ofproto.OFPP_CONTROLLER, actions, data=pkt.data)

    def send_arp_request_flood(self, datapath, target_ip):
        # Broadcast ARP Request to find unknown IP
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_ARP, dst='ff:ff:ff:ff:ff:ff', src=self.GW_MAC))
        pkt.add_protocol(arp.arp(opcode=arp.ARP_REQUEST, src_mac=self.GW_MAC, src_ip='10.0.100.1', dst_mac='00:00:00:00:00:00', dst_ip=target_ip))
        pkt.serialize()
        actions = [datapath.ofproto_parser.OFPActionOutput(datapath.ofproto.OFPP_FLOOD)]
        self._packet_out(datapath, None, datapath.ofproto.OFPP_CONTROLLER, actions, data=pkt.data)

    def _packet_out(self, datapath, msg, in_port, actions, data=None):
        if msg: data = msg.data
        if not data: return
        out = datapath.ofproto_parser.OFPPacketOut(datapath=datapath, buffer_id=datapath.ofproto.OFP_NO_BUFFER, in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
