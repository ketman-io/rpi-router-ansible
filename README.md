# Raspberry Pi Router with Tailscale and Optional Internal DNS/DHCP

This Ansible role configures a Raspberry Pi (tested on Pi 5 with Raspberry Pi OS Bookworm) as a full-featured router with:

- Static IP on LAN interface
- DHCP client on WAN
- NAT routing
- Tailscale (Exit Node + Subnet Router)
- Optional internal DNS + DHCP server (bind9 + isc-dhcp-server)
  - Supports DNS-over-TLS (DoT) with upstream resolvers (1.1.1.1 and 8.8.8.8) via Stubby

## Hardware Requirements

This project has been tested using:

- Raspberry Pi 5 (8GB RAM, but **4GB RAM minimum** is recommended)
- PCIe to MiniPCIe / Gigabit Ethernet / USB 3.2 Gen1 HAT for Raspberry Pi 5 (for dual Ethernet capability)
- A MiniPCIe slot is available and will support a WiFi card in the future (planned feature).

Future improvements will include:
- WiFi card support for the MiniPCIe slot
- BMX7 mesh networking integration
- Remote monitoring via Grafana Alloy agent, shipping logs and metrics to a central Loki+Grafana instance (e.g., on GCP)

## Features

- ✅ Tailscale exit node + subnet routing
- ✅ Optional use of internal DNS-over-TLS + DHCP
- ✅ Full Ansible-driven setup — repeatable, idempotent
- ✅ Cleans conflicting services (`systemd-resolved`, `dnsmasq`) automatically
- ✅ Secure DNS-over-TLS (DoT) via Stubby even for simple mode
- ✅ Designed for self-hosters, developers, and tinkerers
- ✅ Future support for centralized monitoring and alerting

## Usage

### 1. Clone and set up
```bash
git clone https://github.com/YOURUSER/rpi-router-ansible.git
cd rpi-router-ansible
```

### 2. Customize your variables
Edit `group_vars/rpi_routers.yml`:

```yaml
lan_iface: eth0
wan_iface: eth1
lan_ip: 192.168.9.1
lan_prefix: 21
lan_cidr: 192.168.8.0/21
dns_server: 192.168.9.31
use_internal_dns_dhcp: true  # or false for simple router mode
```

Create a secrets file (not committed):
```yaml
# secrets.yml
tailscale_authkey: tskey-XXXXXXXXXXXXXXXXXXXXXXXXXX
```

And add to `.gitignore`:
```bash
echo "secrets.yml" >> .gitignore
```

### 3. Run the playbook
```bash
ansible-playbook -i inventory.ini playbook.yml --extra-vars="@secrets.yml"
```

## Modes

### Advanced mode (`use_internal_dns_dhcp: true`)
- Uses existing custom internal bind9 DNS + DHCP server.
- Suitable for networks with a pre-existing advanced DNS server.
- Good for running fully internal DNS-over-TLS (DoT).
- Still disables systemd-resolved and ensures correct local DNS pointing.

### Simple mode (`use_internal_dns_dhcp: false`)
- Pi router installs and configures bind9 and isc-dhcp-server automatically.
- Pi acts as the DHCP server for the network.
- Pi acts as the DNS server, forwarding all queries securely to Cloudflare (1.1.1.1) and Google DNS (8.8.8.8) **via Stubby using DNS-over-TLS**.
- No need for an external DNS/DHCP server.

## Internal DHCP/DNS Details

Regardless of mode:
- The router disables `systemd-resolved` if active.
- `/etc/resolv.conf` is configured to use the defined internal DNS server.

When `use_internal_dns_dhcp: false`, additionally:
- The router leases addresses in the 192.168.9.100-192.168.9.200 range.
- Assigns itself (192.168.9.1) as the gateway and DNS server to clients.
- Installs and manages bind9 and isc-dhcp-server.
- Installs and configures Stubby to securely forward DNS-over-TLS to upstream providers.
- Cleans up any conflicting services like `dnsmasq`.

## Dependencies
- Raspberry Pi OS Bookworm (Debian 12 base)
- Ansible 2.10+

## To Do
- [ ] Add validation playbook
- [ ] Add automatic tests
- [ ] Integrate optional WiFi support for MiniPCIe card
- [ ] Integrate BMX7 for mesh networking
- [ ] Implement Alloy agent for remote logging to centralized Loki instance

---

This is my first public contribution to my project on privacy and security. There will be more contributions coming soon.
Maintained with ❤️ by a sysadmin who misses running their own mail server.

---

## Project Structure

```plaintext
├── inventory.ini
├── playbook.yml
├── group_vars/
│   └── rpi_routers.yml
├── secrets.sample.yml
├── roles/
│   └── rpi_router/
│       ├── tasks/
│       │   ├── main.yml
│       │   ├── interfaces_nmcli.yml
│       │   ├── ip_forwarding.yml
│       │   ├── firewall.yml
│       │   ├── systemd_dns_cleanup.yml
│       │   ├── dns_dhcp.yml
│       │   ├── stubby.yml
│       │   └── tailscale.yml
│       └── templates/
│           ├── dhcpd.conf.j2
│           └── named.conf.options.j2
├── .gitignore
└── README.md
```
