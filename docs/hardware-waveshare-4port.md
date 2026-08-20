# Hardware: Waveshare PCIE TO 4-CH 2.5G ETH Board (B)

Reference: https://www.waveshare.com/wiki/PCIE_TO_4-CH_2.5G_ETH_Board_(B)

A Raspberry Pi 5 PCIe-x1-to-4-port board built on a VL805 USB/PCIe bridge
feeding four RTL8156 2.5GbE USB Ethernet controllers. This role treats it as
four ordinary LAN interfaces bridged together — nothing in the role is
specific to this board beyond the PCIe enablement below, so any other
PCIe/USB multi-port NIC works the same way: list its interfaces in
`lan_ifaces`.

## Enabling the PCIe slot

The Raspberry Pi 5's external PCIe x1 connector is **off by default**. Until
it is enabled, the board (and anything else in that slot) is invisible —
`lspci` shows only the SoC's own internal RP1 south-bridge, on a different
PCIe domain than the external slot.

This role's `tasks/pcie.yml` adds:

```
dtparam=pciex1
```

to `/boot/firmware/config.txt` — Trixie's boot config path (not
`/boot/config.txt`, which is where it lived on Bullseye and earlier). A
**reboot is required** before the change takes effect; the role prints a
reminder rather than rebooting for you, since a router being reconfigured
remotely is exactly the kind of host you do not want a role rebooting
without being asked.

Deliberately **Gen2, not Gen3** (`pcie_gen3: false`, the default). Gen3 is
available on the Pi 5 and this role can enable it
(`pcie_gen3: true`), but the Waveshare board only speaks Gen2 — forcing Gen3
buys nothing for it and is not the tested configuration.

## Verifying after reboot

```bash
lspci -nnk
```

Expect to see, in addition to the RP1 south-bridge:

```
0000:01:00.0 USB controller [0c03]: VIA Technologies, Inc. VL805/806 xHCI USB 3.0 Controller [1106:3483]
```

with four RTL8156 devices hanging off the resulting USB bus (`lsusb`,
`lsusb -t`). If instead `dmesg | grep pcie` shows `link down` on the
external PCIe host bridge after a reboot with `dtparam=pciex1` confirmed
present in `config.txt`, that is a **physical-layer problem, not a software
one** — check the board is fully seated in the PCIe slot/FFC connector and
that it has power. No amount of `pci=...` kernel arguments, `nft`, or
NetworkManager configuration fixes a PCIe link that never trains; this role
does not attempt to.

## Interface naming

Do not assume the four ports enumerate as `eth1`–`eth4`, or in any
particular left-to-right order matching the board's silkscreen. USB
Ethernet interface naming depends on enumeration order behind the VL805,
which is not guaranteed stable across reboots on every kernel/udev
combination.

Discover the real, permanent identity of each port:

```bash
ip -br link                          # what the kernel currently calls them
for i in $(ip -br link | awk '{print $1}' | grep -v '^lo$'); do
  echo "== $i =="
  ethtool -i "$i" | grep -E 'driver|bus-info'
  ethtool -P "$i"                    # permanent (burned-in) MAC address
done
lsusb -t                             # confirms four devices under the VL805's hub
udevadm info -q path /sys/class/net/<iface>
```

Record the **permanent MAC address** of each port (from `ethtool -P`, not
the possibly-randomised "current" one) against its physical port position
(read the board's silkscreen or trace the cable) once, by hand, while
looking at the physical hardware. That mapping is what makes `lan_ifaces`
reproducible: list interfaces by whatever name the kernel gives them today,
but keep the MAC-to-port record next to your inventory so a future kernel
that renumbers them can be corrected by MAC rather than by guessing which
cable is which again.

This role deliberately does not try to guess or rename interfaces for you —
that decision belongs with whoever is looking at the actual board.
