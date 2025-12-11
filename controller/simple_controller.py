import json
import time
import pprint
from operator import attrgetter
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4, ether_types
from ryu.lib import hub
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from webob import Response

# --- CONFIGURATION ---
CONGESTION_THRESHOLD = 4000000  # 4MB/s ~ 32Mbps (Warning Threshold)
MONITOR_INTERVAL = 2            # Monitor every 2 seconds

simple_switch_instance_name = 'simple_switch_api_app'
url = '/router/{dpid}'

# ANSI color codes for pretty logging
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

class AntiLoopController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(AntiLoopController, self).__init__(*args, **kwargs)
        self.logger.info(f"{Colors.GREEN}--> [SYSTEM] Controller V2 Debug Ready.{Colors.RESET}")
        
        wsgi = kwargs['wsgi']
        wsgi.register(RestRouterController, {simple_switch_instance_name: self})

        self.GATEWAY_MAC = "00:00:00:00:01:00"
        self.CLOUD_MAC   = "00:00:00:00:00:FF" 
        
        self.datapaths = {}
        self.groups_installed = {} 
        self.prev_stats = {} 
        self.monitor_thread = hub.spawn(self._monitor)

        self.static_arp_table = {
            "10.0.100.2": self.CLOUD_MAC,
            "10.0.200.2": self.CLOUD_MAC,
            "10.0.1.1": "00:00:00:00:00:01", "10.0.1.2": "00:00:00:00:00:02",
            "10.0.1.3": "00:00:00:00:00:03", "10.0.2.4": "00:00:00:00:00:04",
            "10.0.2.5": "00:00:00:00:00:05", "10.0.3.6": "00:00:00:00:00:06",
            "10.0.3.7": "00:00:00:00:00:07", "10.0.4.8": "00:00:00:00:00:08",
            "10.0.4.9": "00:00:00:00:00:09", "10.0.4.10": "00:00:00:00:00:0a",
        }

        # --- DEFAULT ROUTING TABLE ---
        self.routing_table = {
            # G1 (Switch 256)
            256: { 
                "10.0.100": 1, "10.0.200": 1, 
                "10.0.1": 2, "10.0.2": 3, "10.0.3": 4, "10.0.4": 5
            },
            # G2 (Switch 512)
            512: { "10.0.3": 2, "default": 1 },
            # G3 (Switch 768)
            768: { 
                "10.0.4": 2,
                "10.0.100": 1, # Default via G1
                "10.0.200": 3, # Direct
                "default": 1 
            }
        }
        self.print_routing_table_pretty()

    # --- FEATURE 1: PRETTY PRINT ROUTING TABLE ---
    def print_routing_table_pretty(self):
        print(f"\n{Colors.BLUE}{'='*60}")
        print(f"{'CURRENT ROUTING TABLE (Static)':^60}")
        print(f"{'='*60}{Colors.RESET}")
        print(f"{'Switch ID':<15} | {'Dest Subnet/IP':<15} | {'Output Port':<10}")
        print("-" * 46)
        
        for dpid, routes in self.routing_table.items():
            first = True
            for dest, port in routes.items():
                sw_name = f"SW-{dpid}" if first else ""
                print(f"{sw_name:<15} | {dest:<15} | {port:<10}")
                first = False
            print("-" * 46)
        print("\n")

    # --- FEATURE 2: MONITOR & CONGESTION WARNING ---
    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                if dp.id in [256, 768]: self._request_stats(dp)
            hub.sleep(MONITOR_INTERVAL)

    def _request_stats(self, datapath):
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, datapath.ofproto.OFPP_ANY)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        
        for stat in body:
            port_no = stat.port_no
            if port_no > 100: continue 
            
            key = (dpid, port_no)
            rx_bytes = stat.rx_bytes
            tx_bytes = stat.tx_bytes
            
            if key in self.prev_stats:
                prev_rx, prev_tx, prev_time = self.prev_stats[key]
                duration = time.time() - prev_time
                if duration > 0:
                    speed_tx = (tx_bytes - prev_tx) / duration
                    speed_rx = (rx_bytes - prev_rx) / duration
                    
                    # RED ALERT LOGIC
                    if speed_tx > CONGESTION_THRESHOLD or speed_rx > CONGESTION_THRESHOLD:
                        max_speed = max(speed_tx, speed_rx) / 1000000
                        print(f"{Colors.RED}[!] CONGESTION ALERT: Switch {dpid} Port {port_no} | Load: {max_speed:.2f} MB/s{Colors.RESET}")
            
            self.prev_stats[key] = (rx_bytes, tx_bytes, time.time())

    # --- FEATURE 3: API & PRE/POST FLOW LOGGING ---
    def change_route(self, dpid, destination_ip, new_port):
        if dpid not in self.datapaths: return False
        datapath = self.datapaths[dpid]
        parser = datapath.ofproto_parser
        
        # 1. Determine destination MAC
        dst_mac = self.static_arp_table.get(destination_ip)
        if not dst_mac and ("10.0.100" in destination_ip or "10.0.200" in destination_ip): 
            dst_mac = self.CLOUD_MAC
        if not dst_mac: return False

        # 2. Log "BEFORE" (Current State)
        # Note: Controller doesn't store old flows in RAM, we log the intent of change
        print(f"\n{Colors.YELLOW}--- [COMMAND RECEIVED] MODIFY FLOW ---{Colors.RESET}")
        print(f"Target Switch : {dpid}")
        print(f"Destination   : {destination_ip}")
        print(f"Old Action    : (Check Routing Table above)")
        print(f"{Colors.GREEN}New Action    : OUTPUT PORT {new_port}{Colors.RESET}")

        # 3. Install New Flow (Action)
        match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=destination_ip)
        actions = [
            parser.OFPActionSetField(eth_src=self.GATEWAY_MAC),
            parser.OFPActionSetField(eth_dst=dst_mac), 
            parser.OFPActionOutput(new_port)
        ]
        
        # Priority 100 to override default flow
        self.add_flow(datapath, 100, match, actions)
        
        print(f"{Colors.BLUE}--> Flow sent to switch successfully.{Colors.RESET}\n")
        return True

    # --- BASIC FUNCTIONS (KEPT AS IS) ---
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.datapaths[datapath.id] = datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority, match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP: return
        
        # Handle ARP
        if eth.ethertype == ether_types.ETH_TYPE_ARP:
            arp_pkt = pkt.get_protocols(arp.arp)[0]
            if arp_pkt.opcode == arp.ARP_REQUEST:
                if arp_pkt.dst_ip.endswith('.254') or arp_pkt.dst_ip.endswith('.1'):
                    self.send_arp_reply(datapath, in_port, arp_pkt.src_mac, self.GATEWAY_MAC, arp_pkt.dst_ip, arp_pkt.src_ip)
                else: self.do_flood(datapath, msg, in_port)
            else: self.do_flood(datapath, msg, in_port)
            return

        # Handle IP Routing
        if eth.ethertype == ether_types.ETH_TYPE_IP:
            ip_pkt = pkt.get_protocols(ipv4.ipv4)[0]
            self.handle_ip_routing(datapath, in_port, ip_pkt, msg)

    def handle_ip_routing(self, datapath, in_port, ip_pkt, msg):
        dpid = datapath.id
        dst_ip = ip_pkt.dst
        
        if dpid in self.routing_table:
            subnet_key = ".".join(dst_ip.split('.')[:3])
            routing_table = self.routing_table.get(dpid, {})
            out_port = routing_table.get(subnet_key)
            if not out_port: out_port = routing_table.get("default")
            
            if out_port:
                dst_mac = self.static_arp_table.get(dst_ip)
                if not dst_mac and ("10.0.100" in dst_ip or "10.0.200" in dst_ip): dst_mac = self.CLOUD_MAC

                if dst_mac:
                    parser = datapath.ofproto_parser
                    actions = []
                    # Default Failover Logic (Priority 10)
                    if dpid == 256 and ("10.0.100" in dst_ip): # G1
                        group_id = 50
                        if dpid not in self.groups_installed:
                            self.add_failover_group(datapath, group_id, 1, 5)
                            self.groups_installed[dpid] = True
                        actions = [parser.OFPActionSetField(eth_src=self.GATEWAY_MAC),
                                   parser.OFPActionSetField(eth_dst=dst_mac),
                                   parser.OFPActionGroup(group_id)]
                    elif dpid == 768 and ("10.0.200" in dst_ip): # G3
                        group_id = 51
                        if dpid not in self.groups_installed:
                            self.add_failover_group(datapath, group_id, 3, 1)
                            self.groups_installed[dpid] = True
                        actions = [parser.OFPActionSetField(eth_src=self.GATEWAY_MAC),
                                   parser.OFPActionSetField(eth_dst=dst_mac),
                                   parser.OFPActionGroup(group_id)]
                    else:
                        actions = [parser.OFPActionSetField(eth_src=self.GATEWAY_MAC),
                                   parser.OFPActionSetField(eth_dst=dst_mac),
                                   parser.OFPActionOutput(out_port)]
                    
                    match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=dst_ip)
                    self.add_flow(datapath, 10, match, actions)
                    
                    data = msg.data if msg.buffer_id == datapath.ofproto.OFP_NO_BUFFER else None
                    out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=data)
                    datapath.send_msg(out)
                else: self.do_flood(datapath, msg, in_port)
            else: self.do_flood(datapath, msg, in_port)
        else: self.do_flood(datapath, msg, in_port)

    def add_failover_group(self, datapath, group_id, main_port, backup_port):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions_main = [parser.OFPActionOutput(main_port)]
        bucket_main = parser.OFPBucket(watch_port=main_port, watch_group=ofproto.OFPG_ANY, actions=actions_main)
        actions_backup = [parser.OFPActionOutput(backup_port)]
        bucket_backup = parser.OFPBucket(watch_port=backup_port, watch_group=ofproto.OFPG_ANY, actions=actions_backup)
        req = parser.OFPGroupMod(datapath, ofproto.OFPGC_ADD, ofproto.OFPGT_FF, group_id, [bucket_main, bucket_backup])
        datapath.send_msg(req)
        self.logger.info(f"Failover Group {group_id} added on SW {datapath.id}")

    def send_arp_reply(self, datapath, port, dst_mac, src_mac, src_ip, dst_ip):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_ARP, dst=dst_mac, src=src_mac))
        pkt.add_protocol(arp.arp(opcode=arp.ARP_REPLY, src_mac=src_mac, src_ip=src_ip, dst_mac=dst_mac, dst_ip=dst_ip))
        pkt.serialize()
        actions = [parser.OFPActionOutput(port)]
        datapath.send_msg(parser.OFPPacketOut(datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER, in_port=ofproto.OFPP_CONTROLLER, actions=actions, data=pkt.data))

    def do_flood(self, datapath, msg, in_port):
        actions = [datapath.ofproto_parser.OFPActionOutput(datapath.ofproto.OFPP_FLOOD)]
        datapath.send_msg(datapath.ofproto_parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=msg.data))

class RestRouterController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(RestRouterController, self).__init__(req, link, data, **config)
        self.app = data[simple_switch_instance_name]

    @route('router', url, methods=['POST'], requirements={'dpid': '[0-9]+'})
    def set_route(self, req, **kwargs):
        dpid = int(kwargs['dpid'])
        try: body = req.json if req.body else {}
        except ValueError: return Response(status=400, body=b"Invalid JSON")
        success = self.app.change_route(dpid, body.get('dest'), int(body.get('port')))
        return Response(status=200, body=b"Route Changed") if success else Response(status=404, body=b"Failed")
