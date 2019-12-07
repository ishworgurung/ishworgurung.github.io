## Three minute guide to set up VLAN on OpenBSD

If you live under the rock, go check out [OpenBSD](https://www.openbsd.org). It's pretty nice. I have been running OpenBSD on my servers for about five years and I absolutely love it. Simplicity, robust, secure and minimal - you name it; It's all there. If you got an old intel 386 or an RaspberryPI, it will be sufficient to run the humble OpenBSD.

Now onto how I VLAN my OpenBSD guest.

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
Watch out for `inet`, `parent`, `vnetid` and `broadcast` in the above listing.

**NB:** Please note that the interfaces that sit between the packet path should all have equal MTUs (e.g. in the above listing, the MTU is 1500). Any switches that sit in between should also support `802.1q` protocol so the VLAN'ed packets can be tagged accordingly. Thanks to _martian67_ for this.

## PSA (Public Service Announcement)

If you run a network with IoT (Internet Of shit Things), consider putting them in a filtered VLAN that can only communicate within the LAN and not to the internet. This is because a lot of these IoT (Internet Of shit Things) *call home* and could potentially ex-filtrate private informations :boom:
