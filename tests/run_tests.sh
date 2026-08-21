#!/bin/bash
# Test runner for rpi-router-ansible. No live host required — everything
# here runs against localhost or pure Jinja2. For live-hardware
# verification (the things a syntax-check or --check cannot prove: a real
# nftables ruleset actually accepted by nft, a real DNS reply actually
# crossing the hairpin, idempotence across a real second converge) see
# docs/critical-infrastructure.md in the fleet repository, which records
# what was actually run against real Trixie/Pi 5 hardware and its result.
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0

echo "== ansible-playbook --syntax-check =="
ansible-playbook -i inventory.ini playbook.yml --syntax-check || fail=1

echo
echo "== template unit tests (pure Jinja2, no Ansible/host needed) =="
python3 tests/test_templates.py || fail=1

echo
echo "== preflight validation: must PASS =="
# vars_file is resolved INSIDE preflight_test.yml, relative to that
# playbook's own directory (tests/), not this script's cwd (the repo
# root) — so the value passed here is "vars/x.yml", not "tests/vars/x.yml".
if ! ansible-playbook tests/preflight_test.yml -e vars_file=vars/good.yml >/tmp/preflight_good.log 2>&1; then
    echo "FAIL: good.yml was refused, and should not have been"
    tail -30 /tmp/preflight_good.log
    fail=1
else
    echo "ok"
fi

echo
echo "== preflight validation: must each be REFUSED =="
for bad in tests/vars/bad_*.yml; do
    name="$(basename "$bad")"
    if ansible-playbook tests/preflight_test.yml -e vars_file="vars/$name" >/tmp/preflight_bad.log 2>&1; then
        echo "FAIL: $name was accepted, and should have been refused"
        tail -30 /tmp/preflight_bad.log
        fail=1
    else
        echo "ok: $name correctly refused"
    fi
done

echo
echo "== legacy variable mapping (old group_vars must keep working) =="
check_mapping() {
    local scenario="$1" expect="$2"
    local out
    out="$(ansible-playbook tests/legacy_mapping_test.yml -e vars_file="vars/$scenario" 2>&1)"
    if echo "$out" | grep -q "RESOLVED.*$expect"; then
        echo "ok: $scenario -> $expect"
    else
        echo "FAIL: $scenario did not resolve to expected: $expect"
        echo "$out" | grep RESOLVED || echo "$out" | tail -20
        fail=1
    fi
}
check_mapping legacy_lan_iface.yml "lan_ifaces=\['eth5'\]"
check_mapping legacy_router_mode_dhcp_dns.yml "manage_dhcp=True manage_dns=True dns_redirect_enabled=False"
check_mapping legacy_router_mode_dns_redirect.yml "manage_dhcp=False manage_dns=False dns_redirect_enabled=True dns_redirect_target=192.168.1.31"
check_mapping legacy_use_internal_dns_dhcp.yml "manage_dhcp=False manage_dns=False dns_redirect_enabled=True dns_redirect_target=192.168.1.31"

echo
echo "== Tailscale is opt-in, not implied =="
if grep -q '^manage_tailscale: true' roles/rpi_router/defaults/main.yml; then
    echo "FAIL: manage_tailscale defaults to true — a router must not imply Tailscale"
    fail=1
else
    echo "ok: manage_tailscale defaults to false"
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "ALL TESTS PASSED"
else
    echo "SOME TESTS FAILED"
fi
exit "$fail"
