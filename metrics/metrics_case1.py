import csv, re, time

# ================================
# Nhập thông tin từ người dùng
# ================================
src_name = input("Source: ").strip()
dst_name = input("Destination: ").strip()
sample_count = int(input("Sample: "))

src = net.get(src_name)
dst = net.get(dst_name)
filename = f'datasetcase1_{src_name}_to_{dst_name}_{sample_count}.csv'

# ================================
# Tạo file CSV
# ================================
with open(filename, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Source', 'Destination', 'Sample', 'Delay_ms', 'Loss_%',
                     'Throughput_TCP_Mbps', 'Throughput_UDP_Mbps', 'Hops'])

print(f"\n*** Collecting {sample_count} TCP & UDP samples from {src_name} → {dst_name} ***\n")

# ================================
# Bắt đầu đo
# ================================
for i in range(1, sample_count + 1):
    print(f"--- Sample {i}/{sample_count} ---")

    # --- Ping ---
    ping_output = src.cmd(f'ping -c 3 {dst.IP()}')
    loss_match = re.search(r'(\d+)% packet loss', ping_output)
    delay_match = re.search(r'rtt min/avg/max/mdev = [\d\.]+/([\d\.]+)/', ping_output)
    loss = float(loss_match.group(1)) if loss_match else 100.0
    delay = float(delay_match.group(1)) if delay_match else 0.0

    # ======================
    # TCP THROUGHPUT
    # ======================
    dst.cmd('pkill iperf >/dev/null 2>&1')
    dst.cmd("bash -c 'iperf -s -p 5001 > /tmp/iperf_server.log 2>&1 &'")
    time.sleep(2)

    src.cmd("rm -f /tmp/iperf_client_tcp.log")
    src.cmd(f"bash -c 'iperf -c {dst.IP()} -p 5001 -t 3 > /tmp/iperf_client_tcp.log 2>&1'")
    dst.cmd('pkill iperf >/dev/null 2>&1')

    tcp_out = src.cmd("cat /tmp/iperf_client_tcp.log")

    tcp_mbps = 0.0
    m = re.search(r'([\d\.]+)\s*(K|M|G)bits/sec', tcp_out)
    if m:
        val, unit = float(m.group(1)), m.group(2)
        if unit == 'K': tcp_mbps = val / 1024
        elif unit == 'M': tcp_mbps = val
        elif unit == 'G': tcp_mbps = val * 1000

    # ======================
    # UDP THROUGHPUT
    # ======================
    dst.cmd('pkill iperf >/dev/null 2>&1')
    dst.cmd("bash -c 'iperf -s -u -p 5002 > /tmp/iperf_udp_server.log 2>&1 &'")
    time.sleep(2)

    src.cmd("rm -f /tmp/iperf_client_udp.log")
    src.cmd(f"bash -c 'iperf -c {dst.IP()} -u -p 5002 -t 3 -b 1000M > /tmp/iperf_client_udp.log 2>&1'")
    dst.cmd('pkill iperf >/dev/null 2>&1')

    udp_out = src.cmd("cat /tmp/iperf_client_udp.log")

    udp_mbps = 0.0
    m2 = re.search(r'([\d\.]+)\s*(K|M|G)bits/sec', udp_out)
    if m2:
        val, unit = float(m2.group(1)), m2.group(2)
        if unit == 'K': udp_mbps = val / 1024
        elif unit == 'M': udp_mbps = val
        elif unit == 'G': udp_mbps = val * 1000

    # --- Traceroute ---
    trace = src.cmd(f'traceroute -n -m 10 {dst.IP()}')
    hops = len(re.findall(r'(?m)^\s*\d+\s', trace))

    # --- Ghi kết quả ---
    with open(filename, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([src_name, dst_name, i, delay, loss, tcp_mbps, udp_mbps, hops])

    print(f"✓ Sample {i}: Delay={delay:.2f} ms | Loss={loss:.1f}% | TCP={tcp_mbps:.2f} Mbps | UDP={udp_mbps:.2f} Mbps | Hops={hops}")
    time.sleep(1)

print(f"\n✅ Done. {sample_count} samples (TCP & UDP) saved to {filename}")
