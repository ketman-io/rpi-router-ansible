# Raspberry Pi Router with Tailscale and Optional Internal DNS/DHCP

This Ansible role configures a Raspberry Pi (tested on Pi 5 with Raspberry Pi OS Trixie/Debian 13) as a full-featured router with:

- Static IP on LAN interface
- DHCP client on WAN
- NAT routing
- Tailscale (Exit Node + Subnet Router)
- Optional internal DNS + DHCP server (bind9 + isc-dhcp-server)
  - DNS-over-TLS (DoT) to an upstream resolver, via bind9's own native DoT forwarding (9.18+) — **no Stubby or other separate DoT proxy**. See `dns_upstream_tls_name` / `dns_upstream_addresses` in `group_vars/rpi_routers.yml`.

## Hardware Requirements

This project has been tested using:

- Raspberry Pi 5 (8GB RAM is recommended, **4GB RAM minimum**)
- PCIe to MiniPCIe / Gigabit Ethernet / USB 3.2 Gen1 HAT for Raspberry Pi 5 (for dual Ethernet capability) [WaveShare](https://www.waveshare.com/pcie-to-minipcie-gbe-usb3.2-hat-plus.htm?srsltid=AfmBOopeyuviONcPUgeMhxCcE_wQWihkKjH78BpAweM9ffbxIXDQbhAF)
- A MiniPCIe slot is available and will support a WiFi card in the future (planned feature).Ex. [WLE900VX](https://compex.com.sg/shop/wifi-module/802-11ac-wave-1/wle900vx-wifi5-11ac-qca9880-qca9890/)

Future improvements will include:
- WiFi card support for the MiniPCIe slot
- BMX7 mesh networking integration
- Remote monitoring via Grafana Alloy agent, shipping logs and metrics to a central Loki+Grafana instance (e.g., on GCP)

## Features

- ✅ Tailscale exit node + subnet routing
- ✅ Optional use of internal DNS-over-TLS + DHCP
- ✅ Full Ansible-driven setup — repeatable, idempotent
- ✅ Cleans conflicting services (`systemd-resolved`, `dnsmasq`) automatically
- ✅ Secure DNS-over-TLS (DoT) via bind9's native forwarder, even in simple mode
- ✅ Designed for self-hosters, developers, and tinkerers
- ✅ Future support for centralized monitoring and alerting

## Usage

### 1. Clone and set up
```bash
git clone https://github.com/ketman-io/rpi-router-ansible.git
cd rpi-router-ansible
```

### 2. Customize your variables
Edit `group_vars/rpi_routers.yml`:

```yaml
lan_iface: eth0
wan_iface: eth1
lan_ip: 192.168.<0-255>.1
lan_prefix: 24
lan_netmask: 255.255.255.0
lan_cidr: 192.168.<0-255>.0/24
dns_server: 192.168.<X.X>
use_internal_dns_dhcp: true  # or false for simple router mode

# Only used in simple mode (use_internal_dns_dhcp: false) — see
# group_vars/rpi_routers.yml for the full set and defaults.
dns_upstream_tls_name: cloudflare-dns.com
dns_upstream_addresses: [1.1.1.1, 1.0.0.1]
dns_client_cidrs: ["{{ lan_cidr }}"]
```

`lan_prefix` and `lan_netmask` must describe the same network — they are not
derived from each other. If your LAN is not a plain /24, set both explicitly
(e.g. a /21: `lan_prefix: 21`, `lan_netmask: 255.255.248.0`).

Create a secrets file (not committed):
```yaml
# secrets.yml
tailscale_authkey: tskey-XXXXXXXXXXXXXXXXXXXXXXXXXX
```

Edit the inventory.ini and set the IP address of your router you are configuring

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
- Pi acts as the DNS server, forwarding all queries over DNS-over-TLS to the
  provider configured in `dns_upstream_tls_name` / `dns_upstream_addresses`
  (Cloudflare by default) — **directly, via bind9's own native DoT
  forwarder**. No separate proxy process is installed or required.
- No need for an external DNS/DHCP server.

## Internal DHCP/DNS Details

Regardless of mode:
- The router disables `systemd-resolved` if active.
- `/etc/resolv.conf` is configured to use the defined internal DNS server.

When `use_internal_dns_dhcp: false`, additionally:
- The router leases addresses in a `.100`–`.200` range on `lan_ip`'s own
  /24, derived from `lan_ip` and `lan_netmask` — not hard-coded to any one
  network. Set `lan_ip`, `lan_cidr`, `lan_prefix` and `lan_netmask` together
  to match your actual LAN; they must agree with each other.
- Assigns itself (`lan_ip`) as the gateway and DNS server to clients.
- Installs and manages bind9 and isc-dhcp-server.
- bind9 forwards recursive queries over native DNS-over-TLS; nothing else is
  installed to do this.
- Cleans up any conflicting services like `dnsmasq`.
- `allow-query`/`allow-recursion` are restricted to `dns_client_cidrs`
  (defaults to your own LAN), not the whole internet.

## Dependencies
- Raspberry Pi OS Trixie (Debian 13) with bind9 9.18+ for native DNS-over-TLS
  forwarding (Trixie ships 9.20). Older releases (Bookworm/Debian 12, bind9
  9.18) also support native DoT; anything with bind9 < 9.18 does not, and
  this role does not fall back to a proxy for it.
- Ansible 2.10+

## To Do
- [ ] Add validation playbook
- [ ] Add automatic tests
- [ ] Integrate optional WiFi support for MiniPCIe card
- [ ] Integrate BMX7 for mesh networking

## Relationship to Fleet

Some routers built from this role are also managed by
[KetmanIO/fleet](https://github.com/KetmanIO/fleet), a private inventory and
convergence tool. Where both are in play, the boundary is:

- **This repo** owns deterministic router functionality: BIND, DHCP,
  NAT/routing, and the Tailscale router behaviour above. Generic, no
  environment-specific data — real IPs, TSIG keys, passwords, and site
  topology belong in a private `group_vars`/inventory override, never here.
- **Fleet** owns host identity, site/criticality metadata, secrets storage
  (TSIG keys, recovery passwords), central logging, and health/observation —
  and, on a Fleet-managed host, it may run its own equivalent BIND role
  (`roles/dns-primary`, `roles/dns-resolver` in the fleet repo) instead of
  this one, so there is one config-management system per file, not two
  fighting over the same paths.

Do not run both this role's `dns_dhcp.yml`/`named.conf.options.j2` and
Fleet's `dns-primary`/`dns-resolver` roles against the same files on the same
host — pick one owner per machine.

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
│       │   └── tailscale.yml
│       └── templates/
│           ├── dhcpd.conf.j2
│           └── named.conf.options.j2
├── .gitignore
└── README.md
```
