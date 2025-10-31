from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, arp
import random, json, os, time


class QLearningSDNController(app_manager.RyuApp):
    """
    Controller điều khiển SDN bằng Q-Learning cho Case 3.
    Học chính sách chọn cổng ra (out_port) dựa trên địa chỉ MAC nguồn & đích.
    """
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(QLearningSDNController, self).__init__(*args, **kwargs)

        # Tham số Q-learning
        self.q_table = {}  # {(src, dst): {port: q_value}}
        self.learning_rate = 0.5
        self.discount = 0.8
        self.epsilon = 0.3  # xác suất chọn hành động ngẫu nhiên (exploration)

        # Các port khả dụng trên switch s1 (tùy vào topo của bạn)
        self.actions = [1, 2, 3, 4, 5, 6, 7]

        # Đường dẫn lưu Q-table
        self.save_path = "/home/npt/SDN_Qlearning_Project/analysis/qtable_case3.json"
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)

        self.last_save_time = time.time()
        self.save_interval = 10  # giây

        self.logger.info("🚀 Q-Learning SDN Controller khởi động thành công!")

    # === Hàm lưu Q-table ra file ===
    def save_qtable(self):
        try:
            # Sửa lỗi bằng cách chuyển keys (tuple) thành chuỗi string
            q_table_str = {str(key): value for key, value in self.q_table.items()}
            with open(self.save_path, "w") as f:
                json.dump(q_table_str, f, indent=2)
            self.logger.info(f"💾 Q-table đã được lưu tại {self.save_path}")
        except Exception as e:
            self.logger.error(f"[ERROR] Không thể lưu Q-table: {e}")

    # === Cài flow mặc định: gửi mọi gói không match lên Controller ===
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        # Flow mặc định: gửi packet_in lên controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=0,
                                match=match, instructions=inst)
        datapath.send_msg(mod)
        self.logger.info("✅ Đã cài flow mặc định gửi lên Controller")

    # === Xử lý packet_in ===
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # === 1️⃣ Xử lý ARP riêng ===
        if eth.ethertype == 0x0806:  # ARP
            self.logger.debug("📡 Gói ARP được flood để học MAC")
            actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
            out = parser.OFPPacketOut(datapath=datapath,
                                      buffer_id=ofproto.OFP_NO_BUFFER,
                                      in_port=in_port,
                                      actions=actions,
                                      data=msg.data)
            datapath.send_msg(out)
            return

        # === 2️⃣ Xử lý IPv4 packet ===
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt is None:
            return

        src, dst = eth.src, eth.dst
        state = (src, dst)

        # Chuyển state (src, dst) thành string
        state_str = str(state)

        # Khởi tạo hàng Q-table mới nếu chưa có
        if state_str not in self.q_table:
            self.q_table[state_str] = {a: 0 for a in self.actions}

        # Chọn hành động (port) theo epsilon-greedy
        if random.random() < self.epsilon:
            action = random.choice(self.actions)
        else:
            action = max(self.q_table[state_str], key=self.q_table[state_str].get)

        # Cập nhật Q-value (mô phỏng reward)
        reward = random.uniform(-1, 1)
        old_value = self.q_table[state_str][action]
        next_max = max(self.q_table[state_str].values())

        new_value = old_value + self.learning_rate * (reward + self.discount * next_max - old_value)
        self.q_table[state_str][action] = round(new_value, 4)

        # === Lưu Q-table định kỳ ===
        if time.time() - self.last_save_time > self.save_interval:
            self.save_qtable()
            self.last_save_time = time.time()

        # === 3️⃣ Cài flow rule cho switch ===
        actions = [parser.OFPActionOutput(action)]
        match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath,
                                priority=1,
                                match=match,
                                instructions=inst)
        datapath.send_msg(mod)

        # === 4️⃣ Gửi lại gói tin hiện tại ra đúng port ===
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=msg.buffer_id,
                                  in_port=in_port,
                                  actions=actions,
                                  data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None)
        datapath.send_msg(out)

        self.logger.info(f"📨 Gói tin {src[:8]}→{dst[:8]} qua cổng {action}, reward={reward:.2f}")
