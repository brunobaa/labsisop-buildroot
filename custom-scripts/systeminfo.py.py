#!/usr/bin/env python3
import json
import os
import re
import socket
import struct
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer


def get_datetime():
    # Não existe um arquivo padrão em /proc/sys para a hora do
    # sistema; usa-se o relógio do próprio SO (datetime.now()).
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_uptime():
    # /proc/uptime: Primeiro valor = segundos desde o boot do sistema
    with open("/proc/uptime", "r") as f:
        uptime_seconds = float(f.readline().split()[0])
    return int(uptime_seconds)


def get_cpu_info():
    model = "Unknown"
    speed_mhz = 0

    # /proc/cpuinfo: "model name" = nome do processador,
    # "cpu MHz" = frequência atual de operação
    if os.path.exists("/proc/cpuinfo"):
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line or "Processor" in line:
                    model = line.split(":", 1)[1].strip()
                elif "cpu MHz" in line:
                    try:
                        speed_mhz = int(float(line.split(":", 1)[1].strip()))
                    except ValueError:
                        pass

    # Fallback: nem todo kernel expõe "cpu MHz" em /proc/cpuinfo;
    # nesse caso lê a frequência atual em /sys (cpufreq), em kHz
    freq_file = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"
    if speed_mhz == 0 and os.path.exists(freq_file):
        try:
            with open(freq_file, "r") as f:
                speed_mhz = int(int(f.read().strip()) / 1000)  # kHz -> MHz
        except Exception:
            pass

    def read_cpu_times():
        # /proc/stat, linha "cpu": tempos acumulados por estado
        # (user, nice, system, idle, iowait, ...); idle + iowait = tempo ocioso
        with open("/proc/stat", "r") as f:
            fields = list(map(int, f.readline().split()[1:]))
            idle_time = fields[3] + fields[4]
            total_time = sum(fields)
            return idle_time, total_time

    try:
        # Porcentagem de uso = variação do tempo ocioso entre duas leituras de /proc/stat
        idle1, total1 = read_cpu_times()
        time.sleep(0.1)
        idle2, total2 = read_cpu_times()

        idle_delta = idle2 - idle1
        total_delta = total2 - total1

        if total_delta > 0:
            usage_percent = round((1.0 - (idle_delta / total_delta)) * 100, 1)
        else:
            usage_percent = 0.0
    except Exception:
        usage_percent = 0.0

    return {
        "model": model,
        "speed_mhz": speed_mhz,
        "usage_percent": usage_percent,
    }


def get_memory_info():
    # /proc/meminfo: uma chave "Nome: valor kB" por linha
    mem_info = {}
    with open("/proc/meminfo", "r") as f:
        for line in f:
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().split()[0]
                mem_info[key] = int(val)

    total_kb = mem_info.get("MemTotal", 0)
    free_kb = mem_info.get("MemFree", 0)
    buffers_kb = mem_info.get("Buffers", 0)
    cached_kb = mem_info.get("Cached", 0)

    total_mb = total_kb // 1024
    # Memória "usada" = total - (livre + buffers + cache)
    used_mb = (total_kb - (free_kb + buffers_kb + cached_kb)) // 1024

    return {"total_mb": total_mb, "used_mb": max(0, used_mb)}


def get_os_version():
    # /proc/version: string com versão do kernel e dados de build
    with open("/proc/version", "r") as f:
        return f.read().strip()


def get_process_list():
    processes = []
    # /proc/<pid>/comm: nome do processo para cada PID listado em /proc
    for pid_dir in os.listdir("/proc"):
        if pid_dir.isdigit():
            comm_path = os.path.join("/proc", pid_dir, "comm")
            if os.path.exists(comm_path):
                try:
                    with open(comm_path, "r") as f:
                        name = f.read().strip()
                    processes.append({"pid": int(pid_dir), "name": name})
                except Exception:
                    continue
    return sorted(processes, key=lambda x: x["pid"])


def get_disks():
    disks = []
    block_dir = "/sys/block"
    if os.path.exists(block_dir):
        # /sys/block/<dev>: um diretório por dispositivo de bloco
        for dev in os.listdir(block_dir):
            # loop* e ram* são dispositivos virtuais, não discos reais
            if dev.startswith("loop") or dev.startswith("ram"):
                continue

            # /sys/block/<dev>/size: tamanho em setores de 512 bytes
            size_file = os.path.join(block_dir, dev, "size")
            if os.path.exists(size_file):
                try:
                    with open(size_file, "r") as f:
                        sectors = int(f.read().strip())

                    size_mb = (sectors * 512) // (1024 * 1024)
                    if size_mb > 0:
                        disks.append(
                            {"device": f"/dev/{dev}", "size_mb": size_mb}
                        )
                except Exception:
                    continue
    return disks


def get_usb_devices():
    usb_list = []
    sys_bus_usb = "/sys/bus/usb/devices"

    if os.path.exists(sys_bus_usb):
        for dev in os.listdir(sys_bus_usb):
            # Filtra só portas físicas (ex: "1-1"), ignorando controladoras
            # ("usb1") e interfaces de um dispositivo ("1-1:1.0")
            if re.match(r"^\d+-\d+(\.\d+)*$", dev):
                dev_path = os.path.join(sys_bus_usb, dev)
                product_file = os.path.join(dev_path, "product")
                manufacturer_file = os.path.join(dev_path, "manufacturer")

                # /sys/bus/usb/devices/<porta>/manufacturer e /product:
                # texto descritivo relatado pelo próprio dispositivo
                description_parts = []
                if os.path.exists(manufacturer_file):
                    try:
                        with open(manufacturer_file, "r") as f:
                            description_parts.append(f.read().strip())
                    except Exception:
                        pass

                if os.path.exists(product_file):
                    try:
                        with open(product_file, "r") as f:
                            description_parts.append(f.read().strip())
                    except Exception:
                        pass

                description = (
                    " ".join(description_parts)
                    if description_parts
                    else "USB Device"
                )
                usb_list.append({"port": dev, "description": description})

    return sorted(usb_list, key=lambda x: x["port"])


def get_network_adapters():
    adapters = []
    net_dir = "/sys/class/net"

    if os.path.exists(net_dir):
        # /sys/class/net/<iface>: um diretório por interface de rede
        for iface in os.listdir(net_dir):
            if iface == "lo":  # loopback não é uma interface física
                continue

            ip_address = None

            # O IP não é exposto como arquivo em /sys; a forma padrão de
            # obtê-lo é via ioctl SIOCGIFADDR (chamada de sistema do kernel)
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                ip_raw = fcntl_ifreq(s.fileno(), iface)
                ip_address = socket.inet_ntoa(ip_raw)
                s.close()
            except Exception:
                # Interface sem IPv4 configurado (ex: sit0) -> não exibe
                ip_address = None

            if ip_address:
                adapters.append({"interface": iface, "ip_address": ip_address})

    return adapters


def fcntl_ifreq(sock_fd, ifname):
    import fcntl

    SIOCGIFADDR = 0x8915  # código ioctl que devolve o IPv4 da interface
    ifreq = struct.pack("256s", ifname[:15].encode("utf-8"))
    res = fcntl.ioctl(sock_fd, SIOCGIFADDR, ifreq)
    return res[20:24]  # bytes 20-23 da struct ifreq = endereço IPv4


class StatusHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        # Endpoint exigido pelo enunciado: GET /status
        if self.path != "/status":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        response = {
            "datetime": get_datetime(),
            "uptime_seconds": get_uptime(),
            "cpu": get_cpu_info(),
            "memory": get_memory_info(),
            "os_version": get_os_version(),
            "processes": get_process_list(),
            "disks": get_disks(),
            "usb_devices": get_usb_devices(),
            "network_adapters": get_network_adapters(),
        }

        data = json.dumps(response, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_server(port=8080):
    print(f"Servidor disponível em http://0.0.0.0:{port}/status")
    server = HTTPServer(("0.0.0.0", port), StatusHandler)
    server.serve_forever()


if __name__ == "__main__":
    run_server()