# Raspberry Pi Router (Ansible)

An Ansible role that turns a Raspberry Pi 5 into a router: NAT to a WAN
uplink, a bridged LAN switch across one or more Ethernet ports, a native
nftables firewall, and independently optional DHCP, DNS, DNS redirection,
and Tailscale. Distilled from two real router deployments — one where a
dedicated host elsewhere runs DHCP/DNS and this router only redirects and
enforces, and one small/remote site where the router reasonably runs
DHCP, authoritative DNS, recursive DNS and DDNS itself, all on one box.
Neither deployment gave this router Tailscale by default; nor does this
role.

Targets **Raspberry Pi OS / Debian 13 (Trixie)**. Earlier releases
(Bookworm) are not supported by this version — see "Upgrading from older
versions" below if you are coming from a Bookworm-era deployment of this
repository.

## Two deployment shapes

**Central-services**: DHCP/DNS already live on another host on your LAN.
This router's job is WAN, NAT, firewall, and (optionally) making sure LAN
clients actually use the intended resolver even if they ignore the
DHCP-advertised one or hardcode a public one.

```
Internet
   │
[this router]  eth0 = WAN (DHCP)
   │            br0  = LAN bridge
  LAN ── existing DHCP/DNS host (e.g. "ns")
```

```yaml
manage_dhcp: false
manage_dns: false
dns_redirect_enabled: true
dns_redirect_target: 192.168.1.31   # your DHCP/DNS host
```

**Self-contained remote site**: no other DHCP/DNS host exists (or it
isn't worth running one). This router is small-site infrastructure:
DHCP, authoritative zones, recursive DNS with native DoT, and DDNS
linking the two, all on one Pi.

```
Internet
   │
[this router]  eth0 = WAN (DHCP)
   │            br0  = LAN bridge
  LAN            DHCP + BIND (authoritative + recursive + DDNS), all here
```

```yaml
manage_dhcp: true
manage_dns: true
dhcp_domain_name: example.internal
dns_authoritative_zones:
  - name: example.internal
    file: /etc/bind/zones/db.example.internal
    dynamic: true
dns_ddns_enabled: true
```

Both are the same role; only the variables differ. "Router + DHCP only"
and "Router + DNS only" are equally valid combinations of the same three
independent capabilities — see "DHCP and DNS" below.

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
- DHCP, DNS, and DNS redirection — three independent, composable
  capabilities (see below), none of them implying the others.
- Tailscale — off by default, fully supported when explicitly enabled.

## Requirements

- Raspberry Pi OS / Debian 13 (Trixie), 64-bit.
- Ansible 2.15+ (ansible-core), plus two collections:
  - `ansible.posix` (for `ansible.posix.sysctl`)
  - `ansible.utils` (for `ansible.utils.in_network`, used to decide whether
    the DNS-redirect NAT hairpin fix is needed — see "DNS redirect and the
    NAT hairpin" below)

  Both ship by default with the Debian `ansible` metapackage. `ansible-core`
  alone needs:
  ```bash
  ansible-galaxy collection install ansible.posix ansible.utils
  ```
- `community.general` (for `community.general.ini_file`, used to disable
  NetworkManager's own `/etc/resolv.conf` management) — also ships with
  the Debian `ansible` metapackage.
- NetworkManager as the network backend (Raspberry Pi OS Trixie's default —
  this role does not use `/etc/network/interfaces`/ifupdown at all).

## Usage

```bash
git clone https://github.com/ketman-io/rpi-router-ansible.git
cd rpi-router-ansible
cp secrets.sample.yml secrets.yml    # fill in only what you actually use; gitignored
```

Edit `inventory.ini` and `group_vars/rpi_routers.yml` for your site — see
"Variables" below for what to set.

```bash
ansible-playbook -i inventory.ini playbook.yml --extra-vars=@secrets.yml
```

Idempotent: running it again against an already-configured router changes
nothing — proven with a real second converge against real hardware, not
assumed (see "Testing" below).

## Variables

Full list with defaults and explanations: `roles/rpi_router/defaults/main.yml`.
The important ones:

| Variable | Meaning |
|---|---|
| `wan_iface` | The interface facing the ISP/upstream router. DHCP client. |
| `lan_ifaces` | List of interfaces to bridge as the LAN switch. One is fine. |
| `lan_bridge` | The bridge name (default `br0`). Owns `lan_ip`. |
| `lan_ip`, `lan_prefix`, `lan_netmask`, `lan_cidr` | The LAN's address. `lan_cidr` is the **network** address (`192.168.1.0/24`), not `lan_ip` with a prefix stapled on. |
| `manage_dhcp` | This router runs `isc-dhcp-server`. |
| `manage_dns` | This router runs BIND (recursive + optional authoritative zones + DDNS). |
| `dns_redirect_enabled`, `dns_redirect_target` | DNAT LAN port-53 traffic to an existing resolver elsewhere. Mutually exclusive with `manage_dns`. |
| `dns_upstream_providers` | Used when `manage_dns: true` — a list of `{name, addresses, tls_hostname}`, see "DNS-over-TLS" below. |
| `dns_authoritative_zones`, `dns_ddns_enabled` | Optional, used when `manage_dns: true` — see "DHCP and DNS" below. |
| `manage_tailscale` | Off by default. See "Tailscale" below. |

## DHCP and DNS

Three independent capabilities, not one mode string — a real deployment
needed "router + DHCP + DNS together" and another needed "neither, just
redirect", and there is no good reason those should be the only two
combinations available:

- **`manage_dhcp: true`** — this router runs `isc-dhcp-server`, restricted
  to the LAN bridge (`INTERFACESv4`), never listening on WAN.
- **`manage_dns: true`** — this router runs BIND, forwarding recursive
  queries directly over native DNS-over-TLS (no Stubby, no local proxy of
  any kind — see "DNS-over-TLS" below). Optionally also authoritative for
  zones you declare (see below).
- **`dns_redirect_enabled: true`** — this router runs neither of the above,
  but transparently redirects LAN-originated port-53 traffic (UDP+TCP) to
  `dns_redirect_target`, so clients get the intended resolver even if they
  ignore the DHCP-advertised one or hardcode a public one. Mutually
  exclusive with `manage_dns` — a router cannot both BE the DNS server and
  redirect to a different one; the role refuses to converge if both are true.

Any combination of `manage_dhcp`/`manage_dns` is valid: neither (a pure
NAT/firewall box — DHCP/DNS live elsewhere entirely, without even the
redirect), DHCP only (something else already runs DNS), DNS only
(something else already runs DHCP), or both (the self-contained shape).

### DNS-over-TLS

No Stubby, no `dnsmasq`, no `systemd-resolved` in the resolution path — this
role actively disables/removes all three. With `manage_dns: true`, BIND
forwards recursive queries directly over TLS on port 853 using the
upstream providers you declare:

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
Recursion and queries are scoped to the LAN (`allow-query`/
`allow-recursion`), never exposed to WAN.

### Authoritative zones and DDNS (optional, self-contained-site shape)

```yaml
manage_dns: true
dhcp_domain_name: example.internal
dns_authoritative_zones:
  - name: example.internal
    file: /etc/bind/zones/db.example.internal
    dynamic: true                  # updated via DDNS from dhcpd
  - name: 1.168.192.in-addr.arpa
    file: /etc/bind/zones/db.192.168.1
    dynamic: true
dns_ddns_enabled: true
dns_ddns_key_name: DDNS_UPDATE      # optional, this is the default
```

The TSIG secret itself is **never** set in `group_vars` — generate one with
`tsig-keygen -a hmac-sha256 <dns_ddns_key_name>` and supply
`dns_ddns_key_secret` via `--extra-vars`, an Ansible Vault file, or your own
secret manager (see `secrets.sample.yml`). The role refuses to render
anything if `dns_ddns_enabled: true` and the secret is empty, rather than
writing a config with no key material.

When `manage_dhcp` is also true, `isc-dhcp-server` registers its own leases
into these zones via the same TSIG key (`ddns-update-style interim`). If
only `manage_dns` is true, some other DHCP server can perform the same
updates using the same key — this role only needs to know the zones and
the key, not who else writes to them.

### DNS redirect and the NAT hairpin

`dns_redirect_target` is very often on the **same subnet** as the LAN
bridge — a dedicated DNS host on the ordinary LAN, not behind a separate
router hop. That case needs more than a DNAT rule: without also
masquerading the redirected flow, the target replies to the client's real
address **directly over the LAN**, bypassing this router entirely, and the
client silently discards the reply as coming from an address it never
queried. This was found with a live packet capture, not assumed from a
syntactically-valid ruleset.

The role computes whether the target is actually on-link
(`ansible.utils.in_network`, in `firewall.yml`) and only adds the hairpin
forward/masquerade rules in that case. A target reachable only via WAN
needs no such rule at all — the ordinary LAN→WAN forward and general WAN
masquerade already cover it, and adding the hairpin rule anyway would be
exactly the kind of NAT rule broader than the situation calls for. Both
cases are covered by `tests/test_templates.py`.

## Firewall

Native nftables (`/etc/nftables.conf`, loaded by the `nftables` systemd
service — no `iptables`, no `iptables-nft` compatibility layer, no
`iptables-persistent`). One `table inet filter` covers IPv4 and IPv6
together; a separate `table ip nat` handles masquerade and (only when
`dns_redirect_enabled`) the DNS-redirect DNAT rule.

Posture: default-drop on input and forward. Router services (SSH, and
DNS/DHCP when this router manages them) are reachable from the LAN bridge
only, never from WAN. Established/related traffic is allowed back in;
nothing else is. `tailscale0` traffic is explicitly accepted — Tailscale
manages its own packet filtering independently once traffic reaches its
tunnel interface, but this ruleset's own default-drop chains run at
standard priority and would otherwise drop tailscale0 traffic before
Tailscale's own rules got a chance to see it.

The rendered ruleset is validated with `nft -c -f` **before** it is
installed; a bad render never reaches the running firewall.

## Tailscale

**Off by default** (`manage_tailscale: false`). A router does not inherently
need Tailscale any more than any other host does — neither of the two real
deployments this role is distilled from gave their router Tailscale by
default; one of them (the remote small-site shape) genuinely uses it, and
enables it explicitly.

To enable: set `manage_tailscale: true` and supply `tailscale_authkey` from
your secrets file (never committed). Installed from Tailscale's own apt
repository (Debian does not carry the package). `tailscale_advertise_exit_node`
and `tailscale_advertise_routes` (defaulting to `lan_cidr`) control what
this router offers the tailnet — both default to off/nothing; a router
that merely runs this role does not automatically advertise routes or
volunteer as an exit node.

If a caller manages Tailscale enrolment itself — Fleet's own `tailscale`
role, for example, which resolves the auth key from a secret store in Go
before Ansible ever runs — leave `manage_tailscale: false` here regardless
of whether Tailscale ends up installed by that other mechanism; this role
then does nothing about Tailscale at all, which is the point.

## PCIe (Raspberry Pi 5 + a PCIe NIC card)

See [docs/hardware-waveshare-4port.md](docs/hardware-waveshare-4port.md).
Short version: the Pi 5's external PCIe slot is off by default;
`enable_pcie: true` (the default) adds `dtparam=pciex1` to
`/boot/firmware/config.txt`, Gen2 only. **A reboot is required** before the
card's interfaces exist — the role tells you when it just made that change
rather than rebooting on its own.

**If the card still isn't detected after that reboot** (`lspci` shows only
the Pi's own internal RP1 south-bridge, and `dmesg` reports the external
PCIe host bridge's link as `link down`), this is a physical-layer problem,
not a software one — confirmed in practice: the fix was reseating the PCIe
FFC ribbon cable, which had been installed backward. These cables are
directional and the retention flap on both ends must close fully; a cable
that looks "in" but is reversed or not fully seated gives exactly this
symptom (the host bridge enumerates, the link never trains). No amount of
`pci=` kernel arguments, `nft`, or NetworkManager configuration fixes a
link that hasn't trained, and this role does not attempt to — reseat the
cable and reboot again.

## Testing

```bash
tests/run_tests.sh
```

No Molecule, no live host required for most of it:

- `ansible-playbook --syntax-check`
- `tests/test_templates.py` — pure-Jinja2 unit tests of every template
  (nftables rendering across the full DHCP/DNS matrix, the redirect hairpin
  present/absent correctly, multi-provider DoT never cross-bound, DDNS
  zone/key rendering, the historical dhcpd netmask bug guarded directly)
- `tests/preflight_test.yml` — every validation in `preflight.yml` exercised
  once for the mistake it should catch, plus one baseline that must pass
- `tests/legacy_mapping_test.yml` — the pre-Trixie variable names still map
  onto the current ones
- a check that `manage_tailscale` still defaults to `false`

What genuinely needs real hardware — a real nftables ruleset actually
accepted by `nft`, a real DNS reply actually crossing the hairpin fix, PCIe
enablement, idempotence across a real second converge — was verified live
against a real Trixie/Pi 5 deployment rather than simulated here. See the
verification commands below, and the [Fleet project's](https://github.com/KetmanIO/fleet)
`docs/critical-infrastructure.md` for the full record of what was actually
run and its result.

### Verification

After a run:

```bash
# Interfaces and bridge
ip -br link
ip -br addr show br0
ls /sys/class/net/br0/brif/        # bridge member interfaces

# Forwarding and firewall
cat /proc/sys/net/ipv4/ip_forward /proc/sys/net/ipv6/conf/all/forwarding
sudo nft list ruleset

# DNS (manage_dns: true)
sudo named-checkconf /etc/bind/named.conf
dig +short example.com @127.0.0.1
sudo tcpdump -ni any tcp port 853  # prove a real DoT connection, not just config

# DNS redirect (dns_redirect_enabled: true), from a real LAN client
dig +short example.com @<lan_ip>

# Tailscale (manage_tailscale: true)
tailscale status
```

## Relationship to Fleet

Some routers built with this role are also managed by
[KetmanIO/fleet](https://github.com/KetmanIO/fleet), a private inventory and
convergence tool. The boundary is deliberate:

- **This repo** owns deterministic router functionality — interfaces,
  firewall, DHCP, DNS, Tailscale — and stays generic. No real IPs, TSIG
  keys, passwords, hostnames, or site topology belong here; those arrive as
  variables from whoever calls this role.
- **Fleet** owns host identity, site/criticality metadata, secrets storage,
  central logging, and health/observation. It includes this repository as a
  git submodule and calls this role directly (its own `roles/router` is a
  thin delegate that sets `manage_tailscale: false` unconditionally, because
  Fleet's own `tailscale` role — a genuinely separate, opt-in capability —
  owns enrolment when a host wants it) rather than re-implementing router
  behaviour a second time.
- On a host where Fleet also runs its own `dns-primary`/`dns-resolver`
  BIND roles for a *different* purpose (e.g. this same Pi is also the
  site's authoritative DNS server, not just its router), pick one owner per
  config file. Do not point two independently-converging roles at
  `/etc/bind/named.conf.options` on the same host.

## Upgrading from older versions

This version replaces:

- `router_mode: dhcp_dns/dns_redirect/passthrough` → `manage_dhcp` +
  `manage_dns` + `dns_redirect_enabled`, three independent booleans instead
  of one mode string. The old variable still works and is mapped
  automatically (`dhcp_dns` → both managed, `dns_redirect` →
  `dns_redirect_enabled`, `passthrough` → neither) — see
  `roles/rpi_router/tasks/legacy_mapping.yml`.
- `use_internal_dns_dhcp: true/false` → the same, via `router_mode` as an
  intermediate step. The old boolean still works. Note the behaviour is not
  identical: the old `false` ("simple mode") ran Stubby *on the router*
  forwarding to Cloudflare/Google; the mapped `dns_redirect_enabled: true`
  runs no local resolver at all and instead redirects to an existing DNS
  host on your network. If you want a router that runs its own resolver,
  set `manage_dns: true` directly (native BIND DoT, not Stubby) instead of
  relying on the legacy mapping.
- `dns_server` → `dns_redirect_target`, mapped automatically.
- `lan_iface` (single interface) → `lan_ifaces` (list) + `lan_bridge`. The
  old name still works — mapped onto a one-item `lan_ifaces` — but new
  deployments should set `lan_ifaces` directly.
- `manage_tailscale` now defaults to **false** (was `true`). A router does
  not imply Tailscale. If you relied on the old default, set
  `manage_tailscale: true` explicitly.
- `/etc/network/interfaces` (ifupdown) configuration → NetworkManager only.
  Trixie's default network backend is NetworkManager; this role no longer
  writes ifupdown config at all.
- Stubby → removed entirely. BIND's own native DoT support (available since
  well before Trixie, and definitely present in Trixie's packaged BIND
  9.20) replaces it directly. If Stubby is installed from a previous run,
  `manage_dns: true` purges it.
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
├── tests/
│   ├── run_tests.sh
│   ├── test_templates.py
│   ├── preflight_test.yml
│   ├── legacy_mapping_test.yml
│   └── vars/
└── roles/
    └── rpi_router/
        ├── defaults/main.yml
        ├── handlers/main.yml
        ├── tasks/
        │   ├── main.yml
        │   ├── legacy_mapping.yml
        │   ├── preflight.yml
        │   ├── pcie.yml
        │   ├── interfaces.yml
        │   ├── ip_forwarding.yml
        │   ├── resolv.yml
        │   ├── dhcp.yml
        │   ├── dns.yml
        │   ├── firewall.yml
        │   └── tailscale.yml
        └── templates/
            ├── named.conf.options.j2
            ├── named.conf.local.j2
            ├── ddns.key.j2
            ├── dhcpd.conf.j2
            └── nftables.conf.j2
```

## To do

- [ ] MiniPCIe WiFi card support.
- [ ] BMX7 mesh networking integration.
- [ ] Alloy agent for remote logging to a centralized Loki instance.

---

This is a personal project shared publicly. Contributions and issue reports
welcome.
