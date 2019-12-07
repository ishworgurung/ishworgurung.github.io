## Two minute guide to set up VLAN on OpenBSD

The `vio0` NIC is based on a QEMU'ed guest on the usual [VIO(4)](https://man.openbsd.org/vio) driver.

Get these files up:

```
$> cat /etc/hostname.vio0 
up
$> cat /etc/hostname.vlan8
inet 10.2.1.61 255.255.255.0 NONE vlan 8 vlandev vio0
up
```

Then restart the network (or simply reboot)

```
$> sh /etc/netstart
```

Then after the `ifconfig` should look like this:

```
$> ifconfig # removed listing of other interfaces for brevity
vio0: flags=8843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	lladdr ab:cd:ef:ab:cd:ef
	index 1 priority 0 llprio 3
	media: Ethernet autoselect
	status: active
vlan8: flags=8843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	lladdr ab:cd:ef:ab:cd:ef
	index 4 priority 0 llprio 3
	encap: vnetid 8 parent vio0 txprio packet rxprio outer
	groups: vlan egress
	media: Ethernet autoselect
	status: active
	inet 10.2.1.61 netmask 0xffffff00 broadcast 10.2.1.255
```
Watch for `inet`, `parent`, `vnetid` and `broadcast` in the above listing.

## PSA (Public Service Announcement)

If you run a network with IoT (of shit things), consider putting them in a filtered VLAN that can only communicate within the LAN and not to the internet. This is because a lot of these IoT (of shit things) *call home* and could ex-filtrate private informations :micdrop:
