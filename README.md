# Raspberry Pi Router (Ansible)

An Ansible role that turns a Raspberry Pi 5 into a router: NAT to a WAN
uplink, a bridged LAN switch across one or more Ethernet ports, a native
nftables firewall, Tailscale, and optional DHCP/DNS with BIND's native
DNS-over-TLS (DoT) upstream — no Stubby, no local DNS proxy of any kind.

Targets **Raspberry Pi OS / Debian 13 (Trixie)**. Earlier releases
(Bookworm) are not supported by this version — see "Upgrading from older
versions" below if you are coming from a Bookworm-era deployment of this
repository.

## What it configures

- WAN: one interface, DHCP client.
- LAN: one or more interfaces bridged together (`br0` by default) as a flat
  switch. The bridge owns the IP address; slave interfaces have none. Tested
  against the [Waveshare PCIE TO 4-CH 2.5G ETH Board (B)](docs/hardware-waveshare-4port.md)
  — four RTL8156 2.5GbE ports behind a VL805 — but `lan_ifaces` is a plain
  list, so this works identically with any number of ports from any vendor.
- IPv4 + IPv6 forwarding.
- A native nftables firewall: masquerade to WAN, default-drop on
  input/forward, no router service ever reachable from WAN.
- DNS/DHCP, in one of three modes (`router_mode` — see below).
- Tailscale, with optional exit-node and subnet-route advertisement.

## Requirements

- Raspberry Pi OS / Debian 13 (Trixie), 64-bit.
- Ansible 2.15+ (ansible-core). Uses `ansible.posix.sysctl` — install the
  `ansible.posix` collection if it is not already present (it ships by
  default with the Debian `ansible` metapackage; `ansible-core` alone needs
  `ansible-galaxy collection install ansible.posix`).
- NetworkManager as the network backend (Raspberry Pi OS Trixie's default —
  this role does not use `/etc/network/interfaces`/ifupdown at all).

## Usage

```bash
git clone https://github.com/ketman-io/rpi-router-ansible.git
cd rpi-router-ansible
cp secrets.sample.yml secrets.yml    # edit in your Tailscale auth key; gitignored
```

Edit `inventory.ini` and `group_vars/rpi_routers.yml` for your site — see
"Variables" below for what to set.

```bash
ansible-playbook -i inventory.ini playbook.yml --extra-vars=@secrets.yml
```

Idempotent: running it again against an already-configured router changes
nothing.

## Variables

Full list with defaults and explanations: `roles/rpi_router/defaults/main.yml`.
The important ones:

| Variable | Meaning |
|---|---|
| `wan_iface` | The interface facing the ISP/upstream router. DHCP client. |
| `lan_ifaces` | List of interfaces to bridge as the LAN switch. One is fine. |
| `lan_bridge` | The bridge name (default `br0`). Owns `lan_ip`. |
| `lan_ip`, `lan_prefix`, `lan_netmask`, `lan_cidr` | The LAN's address. `lan_cidr` is the **network** address (`192.168.1.0/24`), not `lan_ip` with a prefix stapled on — it is used for firewall matches and the Tailscale-advertised route, both of which reject or misbehave on a CIDR with host bits set. |
| `router_mode` | `dhcp_dns`, `dns_redirect`, or `passthrough` — see below. |
| `dns_redirect_target` | Used only in `dns_redirect` mode: the real resolver to transparently redirect LAN DNS traffic to. |
| `dns_upstream_providers` | Used only in `dhcp_dns` mode: a list of `{name, addresses, tls_hostname}` — see "DNS-over-TLS" below. |
| `tailscale_authkey` | From your secrets file, never committed. |
| `tailscale_advertise_exit_node`, `tailscale_advertise_routes` | Router-specific Tailscale behaviour. |

### `router_mode`

- **`dhcp_dns`** — this Pi is the LAN's only DHCP/DNS server. Installs and
  configures `isc-dhcp-server` and `bind9`, the latter forwarding
  recursively over native BIND DNS-over-TLS. Use this when there is no
  other DHCP/DNS host on the network.

- **`dns_redirect`** — this Pi runs **neither** DHCP nor DNS. An existing
  host already serves both. This router transparently redirects
  LAN-originated port-53 traffic (UDP+TCP) to `dns_redirect_target` via
  nftables DNAT, so clients get the intended resolver even if they ignore
  the DHCP-advertised one. This is a common real deployment shape: a
  dedicated DNS/DHCP host already exists on the network, and the router's
  job is NAT and enforcement, not DNS service.

- **`passthrough`** — this Pi does nothing about DNS or DHCP. Pure
  NAT/firewall box. LAN clients need DHCP/DNS reachable from elsewhere
  without this router's help.

### DNS-over-TLS

No Stubby, no `dnsmasq`, no `systemd-resolved` in the resolution path — this
role actively disables/removes all three. In `dhcp_dns` mode, BIND forwards
recursive queries directly over TLS on port 853 using the upstream
providers you declare:

```yaml
dns_upstream_providers:
  - name: cloudflare
    addresses: [1.1.1.1, 1.0.0.1]
    tls_hostname: cloudflare-dns.com
  - name: google
    addresses: [8.8.8.8, 8.8.4.4]
    tls_hostname: dns.google
```

Each provider's addresses are bound to a `tls` profile keyed to **that
provider's own** `tls_hostname` (BIND 9.18+'s per-address `port 853 tls
<profile>` forwarders syntax). An address is never validated against a
different provider's certificate name — mixing providers under one TLS
identity would silently defeat the point of remote-hostname checking.

## Firewall

Native nftables (`/etc/nftables.conf`, loaded by the `nftables` systemd
service — no `iptables`, no `iptables-nft` compatibility layer, no
`iptables-persistent`). One `table inet filter` covers IPv4 and IPv6
together; a separate `table ip nat` handles masquerade and (only in
`dns_redirect` mode) the DNS-redirect DNAT rule.

Posture: default-drop on input and forward. Router services (SSH, and DNS
+DHCP in `dhcp_dns` mode) are reachable from the LAN bridge only, never from
WAN. Established/related traffic is allowed back in; nothing else is.
`tailscale0` traffic is explicitly accepted — Tailscale manages its own
packet filtering independently once traffic reaches its tunnel interface,
but this ruleset's own default-drop chains run at standard priority and
would otherwise drop tailscale0 traffic before tailscale's own rules got a
chance to see it.

The rendered ruleset is validated with `nft -c -f` **before** it is
installed; a bad render never reaches the running firewall.

## Tailscale

Installed from Tailscale's own apt repository (added by this role — Debian
does not carry the `tailscale` package). `tailscale_authkey` comes from your
secrets file. `tailscale_advertise_exit_node` and
`tailscale_advertise_routes` (defaulting to `lan_cidr`) control what this
router offers the tailnet.

If a caller manages Tailscale enrolment itself — Fleet's own `tailscale`
role, for example — set `manage_tailscale: false` to skip this role's
`tailscale up` invocation entirely while still getting everything else
(interfaces, firewall, DNS/DHCP, PCIe).

## PCIe (Raspberry Pi 5 + a PCIe NIC card)

See [docs/hardware-waveshare-4port.md](docs/hardware-waveshare-4port.md).
Short version: the Pi 5's external PCIe slot is off by default;
`enable_pcie: true` (the default) adds `dtparam=pciex1` to
`/boot/firmware/config.txt`, Gen2 only. **A reboot is required** before the
card's interfaces exist — the role tells you when it just made that change
rather than rebooting on its own.

## Upgrading from older versions

This version replaces:

- `lan_iface` (single interface) → `lan_ifaces` (list) + `lan_bridge`. The
  old name still works — a single `lan_iface` is mapped onto a one-item
  `lan_ifaces` automatically — but new deployments should set `lan_ifaces`
  directly.
- `use_internal_dns_dhcp: true/false` → `router_mode: dhcp_dns/dns_redirect`.
  The old boolean still works and is mapped automatically. Note the
  behaviour is not identical: the old `false` ("simple mode") ran Stubby
  *on the router* forwarding to Cloudflare/Google; the new `dns_redirect`
  mode runs no local resolver at all and instead redirects to an existing
  DNS host on your network. If you want a router that runs its own
  resolver, use `router_mode: dhcp_dns` (which uses native BIND DoT, not
  Stubby) instead of relying on the legacy mapping.
- `dns_server` → `dns_redirect_target`, mapped automatically.
- `/etc/network/interfaces` (ifupdown) configuration → NetworkManager only.
  Trixie's default network backend is NetworkManager; this role no longer
  writes ifupdown config at all.
- Stubby → removed entirely. BIND's own native DoT support (available since
  well before Trixie, and definitely present in Trixie's packaged BIND
  9.20) replaces it directly. If Stubby is installed from a previous run,
  `dhcp_dns` mode purges it.
- `iptables`/`iptables-persistent` → native nftables. If migrating a router
  that has never run this role's nftables task, `iptables-persistent`'s
  saved rules are not touched or removed automatically; remove that package
  yourself once you have confirmed the new firewall behaves as expected.

## Project structure

```plaintext
├── inventory.ini
├── playbook.yml
├── group_vars/
│   └── rpi_routers.yml
├── secrets.sample.yml
├── docs/
│   └── hardware-waveshare-4port.md
└── roles/
    └── rpi_router/
        ├── defaults/main.yml
        ├── handlers/main.yml
        ├── tasks/
        │   ├── main.yml
        │   ├── preflight.yml
        │   ├── pcie.yml
        │   ├── interfaces.yml
        │   ├── ip_forwarding.yml
        │   ├── resolv.yml
        │   ├── dns_dhcp.yml
        │   ├── dns_redirect.yml
        │   ├── firewall.yml
        │   └── tailscale.yml
        └── templates/
            ├── named.conf.options.j2
            ├── dhcpd.conf.j2
            └── nftables.conf.j2
```

## Verification

After a run:

```bash
# Interfaces and bridge
ip -br link
ip -br addr show {{ lan_bridge }}
bridge link

# Forwarding and firewall
sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding
sudo nft list ruleset

# DNS (dhcp_dns mode)
sudo named-checkconf /etc/bind/named.conf
dig +short example.com @127.0.0.1
sudo ss -tnp | grep :853        # or: sudo tcpdump -ni any tcp port 853

# Tailscale
tailscale status
```

## To do

- [ ] Automated tests beyond `--syntax-check`/`--check` (this role has been
      exercised live against real Trixie/Pi 5 hardware in both `dhcp_dns`
      and `dns_redirect` modes, in `--check` mode; a Molecule-style
      integration test is not yet part of this repository).
- [ ] MiniPCIe WiFi card support.
- [ ] BMX7 mesh networking integration.
- [ ] Alloy agent for remote logging to a centralized Loki instance.

---

This is a personal project shared publicly. Contributions and issue reports
welcome.
