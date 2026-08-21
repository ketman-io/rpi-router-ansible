#!/usr/bin/env python3
"""Template unit tests for the rpi_router role.

Pure Jinja2, no Ansible runtime and no live host required — these test the
templates' logic directly, the way a syntax-check or a --check run cannot:
whether a specific line is present or absent for a given variable
combination. Run with: python3 tests/test_templates.py
(or via tests/run_tests.sh, which also does the things that DO need
Ansible/a real host).

Every scenario here is one this project got wrong at least once while
building it against real hardware — see docs/hardware-waveshare-4port.md
and the git history of roles/rpi_router/templates/nftables.conf.j2. A test
failure here means a template regressed one of those, silently, in a way
`--syntax-check` cannot catch (a syntactically valid nftables ruleset that
is still the WRONG ruleset).
"""

import pathlib
import sys
import unittest

import jinja2

ROLE = pathlib.Path(__file__).resolve().parent.parent / "roles" / "rpi_router"
TEMPLATES = ROLE / "templates"

def _ansible_bool(value):
    """Minimal stand-in for Ansible's `bool` Jinja filter, which plain
    Jinja2 does not ship. Good enough for the values these templates
    actually pass through it: real bools, and the yes/no/true/false
    strings a CLI -e override might supply."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("yes", "true", "1", "on")
    return bool(value)


env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)))
env.filters["bool"] = _ansible_bool


def render(name, **variables):
    return env.get_template(name).render(**variables)


def config_lines(rendered):
    """Rendered config with comment lines stripped, for assertions that
    must not be fooled by a comment's own explanatory text mentioning the
    very value it warns against (see nftables.conf.j2 / dhcpd.conf.j2's
    comments about the historical bugs they fixed)."""
    return "\n".join(
        line for line in rendered.splitlines()
        if not line.strip().startswith(("#", "//"))
    )


# Base variable set every render needs, mirroring defaults/main.yml's shapes
# closely enough to exercise the templates realistically. Individual tests
# override just what they're testing.
BASE = dict(
    wan_iface="eth0",
    lan_ifaces=["eth1"],
    lan_bridge="br0",
    lan_bridge_stp=False,
    lan_ip="192.168.1.1",
    lan_prefix=24,
    lan_netmask="255.255.255.0",
    lan_cidr="192.168.1.0/24",
    manage_dhcp=False,
    manage_dns=False,
    dns_redirect_enabled=False,
    dns_redirect_target="",
    rpi_router_dns_redirect_hairpin_needed=False,
    dhcp_range_start="192.168.1.100",
    dhcp_range_end="192.168.1.200",
    dhcp_default_lease_time=600,
    dhcp_max_lease_time=7200,
    dhcp_domain_name="",
    dhcp_ntp_servers=[],
    dns_upstream_providers=[
        dict(name="cloudflare", addresses=["1.1.1.1", "1.0.0.1"], tls_hostname="cloudflare-dns.com"),
    ],
    dns_authoritative_zones=[],
    dns_ddns_enabled=False,
    dns_ddns_key_name="DDNS_UPDATE",
    dns_ddns_key_algorithm="hmac-sha256",
    tailscale_allow_wan_udp=False,
    tailscale_udp_port=41641,
)


def nft(**overrides):
    v = dict(BASE, **overrides)
    return render("nftables.conf.j2", **v)


def named_options(**overrides):
    v = dict(BASE, **overrides)
    return render("named.conf.options.j2", **v)


def named_local(**overrides):
    v = dict(BASE, **overrides)
    return render("named.conf.local.j2", **v)


def dhcpd(**overrides):
    v = dict(BASE, **overrides)
    return render("dhcpd.conf.j2", **v)


class NftablesDnsDhcpGating(unittest.TestCase):
    """manage_dhcp/manage_dns are independent — the firewall's own LAN-side
    accept rules for port 53/67 must follow each one separately, not a
    single combined mode."""

    def test_neither_managed_no_service_ports_open(self):
        r = nft(manage_dhcp=False, manage_dns=False)
        self.assertNotIn("dport 53 accept", r)
        self.assertNotIn("dport 67 accept", r)

    def test_dns_only(self):
        r = nft(manage_dhcp=False, manage_dns=True)
        self.assertIn('dport 53 accept', r)
        self.assertNotIn("dport 67 accept", r)

    def test_dhcp_only(self):
        r = nft(manage_dhcp=True, manage_dns=False)
        self.assertIn("dport 67 accept", r)
        self.assertNotIn("dport 53 accept", r)

    def test_both(self):
        r = nft(manage_dhcp=True, manage_dns=True)
        self.assertIn("dport 53 accept", r)
        self.assertIn("dport 67 accept", r)


class NftablesDnsRedirectHairpin(unittest.TestCase):
    """The DNS-redirect NAT hairpin bug: DNAT alone is not enough when the
    target is on the LAN's own subnet, and the masquerade-everything fix
    for that must NOT apply when the target is genuinely external — see
    firewall.yml's ansible.utils.in_network computation, mocked here via
    rpi_router_dns_redirect_hairpin_needed directly since this is a
    template-only test."""

    def test_redirect_disabled_no_dnat_at_all(self):
        r = nft(dns_redirect_enabled=False, dns_redirect_target="")
        self.assertNotIn("dnat to", r)
        self.assertNotIn("ip daddr", r)

    def test_redirect_to_on_lan_target_gets_hairpin(self):
        r = nft(
            dns_redirect_enabled=True,
            dns_redirect_target="192.168.1.31",
            rpi_router_dns_redirect_hairpin_needed=True,
        )
        self.assertIn('dnat to 192.168.1.31:53', r)
        self.assertIn('iifname "br0" oifname "br0" ip daddr 192.168.1.31 accept', r)
        self.assertIn("ip daddr 192.168.1.31 udp dport 53 masquerade", r)
        self.assertIn("ip daddr 192.168.1.31 tcp dport 53 masquerade", r)

    def test_redirect_to_external_target_no_hairpin(self):
        """The bug this guards: a target reachable only via WAN needs no
        LAN->LAN forward hole and no extra masquerade rule — the ordinary
        LAN->WAN forward + general WAN masquerade already cover it. Adding
        the hairpin rules anyway would be exactly the "NAT rules broader
        than necessary" this project was told not to write."""
        r = nft(
            dns_redirect_enabled=True,
            dns_redirect_target="9.9.9.9",
            rpi_router_dns_redirect_hairpin_needed=False,
        )
        self.assertIn("dnat to 9.9.9.9:53", r)
        self.assertNotIn('oifname "br0" ip daddr', r)
        self.assertNotIn("ip daddr 9.9.9.9", r.replace("dnat to 9.9.9.9:53", ""))


class NftablesTailscale(unittest.TestCase):
    def test_wan_udp_closed_by_default(self):
        r = nft(tailscale_allow_wan_udp=False)
        self.assertNotIn("udp dport 41641", r)

    def test_wan_udp_opened_when_requested(self):
        r = nft(tailscale_allow_wan_udp=True, tailscale_udp_port=41641)
        self.assertIn('iifname "eth0" udp dport 41641 accept', r)

    def test_tailscale_interface_always_trusted_regardless_of_mode(self):
        # tailscale0 is accepted unconditionally in both input and forward —
        # this is not gated by manage_tailscale at all, because a host may
        # have Tailscale from outside this role's management (see Fleet's
        # own tailscale role) and this ruleset must still not fight it.
        r = nft()
        self.assertIn('iifname "tailscale0" accept', r)
        self.assertIn('oifname "tailscale0" accept', r)


class NftablesMultipleLanInterfaces(unittest.TestCase):
    """The template itself only ever refers to lan_bridge, never to
    individual lan_ifaces entries — bridging N interfaces is an
    interfaces.yml/NetworkManager concern, not a firewall one. This is the
    property that makes 1 LAN port and 4 (Waveshare) the same code path."""

    def test_single_interface(self):
        r1 = nft(lan_ifaces=["eth1"])
        r4 = nft(lan_ifaces=["eth1", "eth2", "eth3", "eth4"])
        self.assertEqual(r1, r4)


class NamedOptionsProviderPairing(unittest.TestCase):
    """Each provider's addresses must be bound to ITS OWN tls profile —
    never checked against a different provider's certificate hostname."""

    def test_single_provider(self):
        r = named_options()
        self.assertIn('remote-hostname "cloudflare-dns.com"', r)
        self.assertIn("1.1.1.1 port 853 tls dot-cloudflare", r)
        self.assertIn("1.0.0.1 port 853 tls dot-cloudflare", r)

    def test_multiple_providers_never_cross_bound(self):
        r = named_options(
            dns_upstream_providers=[
                dict(name="cloudflare", addresses=["1.1.1.1", "1.0.0.1"], tls_hostname="cloudflare-dns.com"),
                dict(name="google", addresses=["8.8.8.8", "8.8.4.4"], tls_hostname="dns.google"),
            ]
        )
        self.assertIn("1.1.1.1 port 853 tls dot-cloudflare", r)
        self.assertIn("1.0.0.1 port 853 tls dot-cloudflare", r)
        self.assertIn("8.8.8.8 port 853 tls dot-google", r)
        self.assertIn("8.8.4.4 port 853 tls dot-google", r)
        # The failure mode this exists to catch: a Google address ending up
        # under Cloudflare's tls profile (or vice versa) because the loops
        # were flattened incorrectly.
        self.assertNotIn("8.8.8.8 port 853 tls dot-cloudflare", r)
        self.assertNotIn("8.8.4.4 port 853 tls dot-cloudflare", r)
        self.assertNotIn("1.1.1.1 port 853 tls dot-google", r)
        self.assertNotIn("1.0.0.1 port 853 tls dot-google", r)
        self.assertIn('remote-hostname "cloudflare-dns.com"', r)
        self.assertIn('remote-hostname "dns.google"', r)

    def test_no_stubby_no_plaintext_forwarders(self):
        r = named_options()
        self.assertIn("forward only;", r)
        self.assertIn("port 853 tls", r)
        self.assertNotIn("8053", r)  # the historical Stubby local port

    def test_recursion_not_exposed_to_wan(self):
        # allow-query/allow-recursion must be scoped to the LAN, never "any"
        r = named_options(lan_cidr="10.0.0.0/24")
        self.assertIn("allow-query { localhost; 10.0.0.0/24; }", r)
        self.assertIn("allow-recursion { localhost; 10.0.0.0/24; }", r)
        self.assertNotIn("{ any; }", r)


class NamedLocalAuthoritativeZones(unittest.TestCase):
    def test_no_zones_renders_empty_ish(self):
        r = named_local(dns_authoritative_zones=[])
        self.assertNotIn("zone \"", r)
        self.assertNotIn("include \"/etc/bind/ddns.key\"", r)

    def test_dynamic_zone_gets_update_policy(self):
        r = named_local(
            dns_ddns_enabled=True,
            dns_authoritative_zones=[
                dict(name="example.internal", file="/etc/bind/zones/db.example.internal", dynamic=True),
            ],
        )
        self.assertIn('zone "example.internal"', r)
        self.assertIn("update-policy { grant DDNS_UPDATE zonesub ANY; }", r)
        self.assertIn('include "/etc/bind/ddns.key";', r)

    def test_static_zone_gets_no_update_policy(self):
        r = named_local(
            dns_authoritative_zones=[
                dict(name="static.example", file="/etc/bind/zones/db.static", dynamic=False),
            ],
        )
        self.assertIn('zone "static.example"', r)
        self.assertNotIn("update-policy", r)


class DhcpdConfNetworkCorrectness(unittest.TestCase):
    """The confirmed real bug this guards: a hard-coded /21 netmask and a
    192.168.9.x range regardless of the site's actual network, which broke
    isc-dhcp-server's own self-test outright on any other-shaped site."""

    def test_uses_declared_network_not_a_default(self):
        r = dhcpd(
            lan_cidr="10.20.30.0/24",
            lan_netmask="255.255.255.0",
            lan_ip="10.20.30.1",
            dhcp_range_start="10.20.30.100",
            dhcp_range_end="10.20.30.200",
        )
        lines = config_lines(r)
        self.assertIn("subnet 10.20.30.0 netmask 255.255.255.0", lines)
        self.assertIn("range 10.20.30.100 10.20.30.200", lines)
        self.assertNotIn("255.255.248.0", lines)
        self.assertNotIn("192.168.9", lines)

    def test_ddns_off_by_default(self):
        r = dhcpd(dns_ddns_enabled=False)
        self.assertNotIn("ddns-updates on", r)
        self.assertNotIn("ddns-update-style", r)

    def test_ddns_on_includes_key_and_zones(self):
        r = dhcpd(
            dns_ddns_enabled=True,
            dhcp_domain_name="example.internal",
            dns_authoritative_zones=[
                dict(name="example.internal", file="x", dynamic=True),
                dict(name="30.20.10.in-addr.arpa", file="y", dynamic=True),
                dict(name="static.example", file="z", dynamic=False),
            ],
        )
        self.assertIn("ddns-update-style interim;", r)
        self.assertIn("ddns-updates on;", r)
        self.assertIn('include "/etc/dhcp/ddns.key";', r)
        self.assertIn("zone example.internal. {", r)
        self.assertIn("zone 30.20.10.in-addr.arpa. {", r)
        # Only dynamic zones get a dhcpd zone stanza.
        self.assertNotIn("zone static.example. {", r)
        self.assertIn('ddns-domainname "example.internal";', r)

    def test_optional_domain_and_ntp_omitted_when_unset(self):
        r = dhcpd(dhcp_domain_name="", dhcp_ntp_servers=[])
        self.assertNotIn("option domain-name ", r)
        self.assertNotIn("option ntp-servers", r)

    def test_optional_domain_and_ntp_present_when_set(self):
        r = dhcpd(dhcp_domain_name="example.internal", dhcp_ntp_servers=["192.168.1.1", "192.168.1.2"])
        self.assertIn('option domain-name "example.internal";', r)
        self.assertIn("option ntp-servers 192.168.1.1, 192.168.1.2;", r)


if __name__ == "__main__":
    sys.exit(unittest.main())
