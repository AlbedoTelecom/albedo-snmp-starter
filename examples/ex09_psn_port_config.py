#!/usr/bin/env python3
"""
Example 09 — PSN Port Configuration
=====================================
Demonstrates how to configure a PSN (Ethernet) test port in two layers:

  Layer 1 — Physical (ATSL-PSN-PORT-MIB, psnPortCfgPhyTable)
    - Connector selection (RJ-45 or SFP)
    - Autonegotiation enable/disable
    - Allowed speeds during autoneg (10/100/1000 Mb/s)
    - Forced bit rate when autoneg is OFF
    - Clock role (auto / master / slave)
    - Laser on/off — ONLY writable when connector = SFP

  Layer 2 — Network identity (ATSL-PSN-GENERATOR-MIB, psnGenModeTable)
    - Port operation mode (txrx, monitor, loopback…)
    - VLAN encapsulation and C-VID (CVID only when encap ≠ untagged)
    - DHCP and static IP — ONLY accessible when psnGenMode = ipEndpoint(2)
      (i.e. FunctionType.PSN_IP_ENDPOINT). In ethEndpoint mode the agent
      returns noAccess for all IP-level OIDs.

CONDITIONAL-ACCESS RULES — enforced by the agent, not by the MIB syntax:
  ┌──────────────────────────────────────────────┬──────────────────────────────┐
  │ OID                                          │ Condition to be writable     │
  ├──────────────────────────────────────────────┼──────────────────────────────┤
  │ psnPortCfgPhyLaserOn                         │ psnPortCfgPhyConnector = SFP │
  │ psnPortCfgPhyForcedBitRate                   │ psnPortCfgPhyAutonegon = OFF │
  │ psnGenModeCvidLocal / psnGenModeCpcpLocal    │ encapsulation ≠ untagged(0)  │
  │ psnGenModeDhcpEnabled / psnGenModeIpv4*      │ psnGenMode = ipEndpoint(2)   │
  └──────────────────────────────────────────────┴──────────────────────────────┘

PortMode values (psnGenModePort):
  0 = disabled, 1 = txrx, 2 = monitor, 3 = loopback, 4 = cable, 5 = link

psnPortCfgPhyForcedBitRate values:
  0 = 10 Mb/s, 1 = 100 Mb/s, 2 = 1 Gb/s, 3 = 10 Gb/s

Usage:
    python ex09_psn_port_config.py <device_ip> [port_index]

Warning:
    This script modifies port parameters. Run only when no active test is
    in progress. Original values are saved and restored at the end.
"""

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_snmp_core import MultifunctionDevice, FunctionType, TRUTH_VALUE
from pysnmp.proto.rfc1902 import OctetString

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEVICE_IP  = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.100'
PORT_INDEX = int(sys.argv[2]) if len(sys.argv) > 2 else 1

PSN_PORT_MIB = 'ATSL-PSN-PORT-MIB'
PSN_GEN_MIB  = 'ATSL-PSN-GENERATOR-MIB'

# Connector type constants (ConnectorType TC)
CONNECTOR_RJ45 = 0
CONNECTOR_SFP  = 1

# TruthValue constants (SNMPv2-TC)
TRUE  = 1   # enabled / on / allowed
FALSE = 2   # disabled / off / not-allowed

# Encapsulation constants (ATSL-MIB::Encapsulation)
ENCAP_UNTAGGED = 0
ENCAP_VLAN     = 1
ENCAP_QINQ     = 2

# psnGenMode constants (EndpointMode TC in ATSL-PSN-GENERATOR-MIB)
PSN_MODE_L1ENDPOINT  = 0
PSN_MODE_ETHENDPOINT = 1
PSN_MODE_IPENDPOINT  = 2

# ---------------------------------------------------------------------------
# Target physical-layer configuration
# ---------------------------------------------------------------------------
# Phase A — always writable (no hardware-state dependency).
# Write these first; the results determine which Phase B OIDs are accessible.
PHY_PHASE_A = {
    'psnPortCfgPhyConnector':         CONNECTOR_RJ45,  # 0=RJ-45, 1=SFP
    'psnPortCfgPhyAutonegotiationOn': TRUE,             # 1=ON, 2=OFF
    'psnPortCfgPhy1000Allowed':       TRUE,
    'psnPortCfgPhy100Allowed':        TRUE,
    'psnPortCfgPhy10Allowed':         FALSE,            # disallow 10 Mb/s
    'psnPortCfgPhyClockRole':         0,                # 0=auto, 1=master, 2=slave
}

# Phase B — conditionally writable:
#   psnPortCfgPhyLaserOn    → only when connector = SFP (1)
#   psnPortCfgPhyForcedBitRate → only when autoneg = OFF (2)
# The write loop below reads the post-Phase-A state before deciding.
PHY_LASER_VALUE        = FALSE   # 1=on, 2=off (only sent if connector=SFP)
PHY_FORCED_RATE_VALUE  = 2       # 0=10M, 1=100M, 2=1G, 3=10G (only sent if autoneg=OFF)

# ---------------------------------------------------------------------------
# Target network-identity configuration
# ---------------------------------------------------------------------------
# Group A — writable in both ethEndpoint and ipEndpoint modes.
NET_GROUP_A = {
    'psnGenModePort':               1,                # 1=txrx (active endpoint)
    'psnGenModeEncapsulationLocal': ENCAP_UNTAGGED,   # 0=untagged, 1=vlan, 2=qinq
}

# Group B — CVID and CoS: only writable when encapsulation ≠ untagged.
# The write loop reads post-Group-A encapsulation before deciding.
NET_CVID_VALUE = 100    # VLAN ID 100 (only sent if encap = vlan or qinq)
NET_CPCP_VALUE = 0      # CoS 0       (only sent if encap = vlan or qinq)

# Group C — IP stack: only writable when psnGenMode (scalar) = ipEndpoint(2).
# The write loop reads the psnGenMode scalar before deciding.
#
# InetAddressIPv4 encoding note:
#   ATSL-PSN-GENERATOR-MIB imports InetAddressIPv4 from INET-ADDRESS-MIB.
#   InetAddressIPv4 is OCTET STRING (SIZE 4) — 4 raw bytes in network byte
#   order, NOT a dotted-decimal ASCII string. Passing a plain Python str to
#   SNMPDevice.set() would wrap it as a 12-byte ASCII OctetString, causing
#   the agent to truncate to the last 4 bytes and store a garbage value.
#   Use ip_to_snmp() to encode correctly before writing.
def ip_to_snmp(dotted: str) -> OctetString:
    """Encode a dotted-decimal IPv4 string as a 4-byte SNMP OctetString."""
    return OctetString(socket.inet_aton(dotted))

def snmp_to_ip(val) -> str:
    """Decode a 4-byte SNMP OctetString back to dotted-decimal."""
    return socket.inet_ntoa(bytes(val))

NET_GROUP_C = {
    'psnGenModeDhcpEnabled':        FALSE,                        # TruthValue integer
    'psnGenModeIpv4AddressStatic':  ip_to_snmp('192.168.10.1'),   # 4-byte OctetString
    'psnGenModeIpv4MaskStatic':     ip_to_snmp('255.255.255.0'),  # 4-byte OctetString
    'psnGenModeIpv4GatewayStatic':  ip_to_snmp('192.168.10.254'), # 4-byte OctetString
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def write_and_verify(device, mib: str, oid: str, value,
                            index: int, timeout: float = 5.0) -> bool:
    """Write a single OID and poll until the device confirms the new value.

    Comparison handles three value types:
      - OctetString (InetAddressIPv4): compared as raw bytes
      - int-coercible (TruthValue, Integer enums): compared as int
      - str fallback for anything else
    """
    ok = await device.set(mib, oid, value, index)
    if not ok:
        print(f"    ✗ SET rejected: {oid} = {value}")
        return False

    deadline = asyncio.get_event_loop().time() + timeout
    readback = None
    while asyncio.get_event_loop().time() < deadline:
        readback = await device.get(mib, oid, index)
        if readback is not None:
            if isinstance(value, OctetString):
                match = bytes(readback) == bytes(value)
                display = snmp_to_ip(value) if len(bytes(value)) == 4 else repr(bytes(value))
            else:
                try:
                    match = int(readback) == int(value)
                except (TypeError, ValueError):
                    match = str(readback) == str(value)
                display = value
            if match:
                print(f"    ✓ {oid} = {display}")
                return True
        await asyncio.sleep(0.2)

    print(f"    ✗ Verification timed out: {oid} — last read: {readback}")
    return False


async def snapshot_phy(device, index: int) -> dict:
    """Read all writable physical OIDs for later restore."""
    oids = (
        list(PHY_PHASE_A.keys()) +
        ['psnPortCfgPhyLaserOn', 'psnPortCfgPhyForcedBitRate']
    )
    return {oid: await device.get(PSN_PORT_MIB, oid, index) for oid in oids}


async def snapshot_net(device, index: int) -> dict:
    """Read all writable network-identity OIDs for later restore."""
    oids = (
        list(NET_GROUP_A.keys()) +
        ['psnGenModeCvidLocal', 'psnGenModeCpcpLocal'] +
        list(NET_GROUP_C.keys())
    )
    return {oid: await device.get(PSN_GEN_MIB, oid, index) for oid in oids}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():

    async with MultifunctionDevice(DEVICE_IP) as device:

        # ------------------------------------------------------------------
        # Step 1: Ensure a PSN function is active (ethEndpoint or ipEndpoint).
        # ------------------------------------------------------------------
        print("=== Step 1: Checking / switching function mode ===")
        PSN_FUNCTIONS = {
            FunctionType.PSN_L1_ENDPOINT,
            FunctionType.PSN_ETH_ENDPOINT,
            FunctionType.PSN_IP_ENDPOINT,
            FunctionType.PSN_EXTERNAL,
        }
        if await device.is_multifunction():
            active = await device.get_active_function()
            if active not in PSN_FUNCTIONS:
                # Device is in TDM or CLKMON — switch to ETH endpoint as default.
                # If already in any PSN sub-mode (including PSN_IP_ENDPOINT),
                # leave it alone so Group C can be exercised.
                ok = await device.ensure_function(FunctionType.PSN_ETH_ENDPOINT)
                if not ok:
                    print("  ERROR: Could not switch to PSN mode.")
                    return
                active = await device.get_active_function()
            print(f"  Active function: {active.name if active else 'unknown'}")
        else:
            print("  Non-multifunction device — assuming PSN mode is active.")

        # Also read the psnGenMode scalar — needed to gate IP-level writes.
        psn_gen_mode_raw = await device.get(PSN_GEN_MIB, 'psnGenMode', 0)
        psn_gen_mode = int(psn_gen_mode_raw) if psn_gen_mode_raw is not None else -1
        gen_mode_label = {
            PSN_MODE_L1ENDPOINT:  'l1Endpoint',
            PSN_MODE_ETHENDPOINT: 'ethEndpoint',
            PSN_MODE_IPENDPOINT:  'ipEndpoint',
        }.get(psn_gen_mode, f'unknown({psn_gen_mode})')
        print(f"  psnGenMode = {psn_gen_mode} ({gen_mode_label})")

        # ------------------------------------------------------------------
        # Step 2: Snapshot current state (for restore at the end).
        # ------------------------------------------------------------------
        print(f"\n=== Step 2: Snapshot current config (port {PORT_INDEX}) ===")
        orig_phy = await snapshot_phy(device, PORT_INDEX)
        orig_net = await snapshot_net(device, PORT_INDEX)
        for oid, val in {**orig_phy, **orig_net}.items():
            print(f"  {oid:42s} = {val}")

        # ------------------------------------------------------------------
        # Step 3: Physical layer — Phase A (always writable).
        # ------------------------------------------------------------------
        print(f"\n=== Step 3: Physical config Phase A — connector + autoneg ===")
        all_ok = True
        for oid, value in PHY_PHASE_A.items():
            result = await write_and_verify(device, PSN_PORT_MIB, oid, value, PORT_INDEX)
            all_ok = all_ok and result

        # ------------------------------------------------------------------
        # Step 4: Physical layer — Phase B (conditionally writable).
        # Read the post-Phase-A state to determine which OIDs are accessible.
        # ------------------------------------------------------------------
        print(f"\n=== Step 4: Physical config Phase B — conditional OIDs ===")

        connector_now = await device.get(PSN_PORT_MIB, 'psnPortCfgPhyConnector', PORT_INDEX)
        autoneg_now   = await device.get(PSN_PORT_MIB, 'psnPortCfgPhyAutonegotiationOn', PORT_INDEX)

        connector_val = int(connector_now) if connector_now is not None else -1
        autoneg_val   = int(autoneg_now)   if autoneg_now   is not None else -1

        if connector_val == CONNECTOR_SFP:
            print(f"  Connector = SFP → writing psnPortCfgPhyLaserOn = {PHY_LASER_VALUE}")
            result = await write_and_verify(
                device, PSN_PORT_MIB, 'psnPortCfgPhyLaserOn', PHY_LASER_VALUE, PORT_INDEX
            )
            all_ok = all_ok and result
        else:
            print(f"  Connector = RJ-45 → skipping psnPortCfgPhyLaserOn (not applicable)")

        if autoneg_val == FALSE:  # autoneg is OFF
            print(f"  Autoneg = OFF → writing psnPortCfgPhyForcedBitRate = {PHY_FORCED_RATE_VALUE}")
            result = await write_and_verify(
                device, PSN_PORT_MIB, 'psnPortCfgPhyForcedBitRate', PHY_FORCED_RATE_VALUE, PORT_INDEX
            )
            all_ok = all_ok and result
        else:
            print(f"  Autoneg = ON → skipping psnPortCfgPhyForcedBitRate (only used when autoneg is OFF)")

        print(f"\n  Physical config overall: {'OK' if all_ok else 'PARTIAL FAILURE'}")

        # ------------------------------------------------------------------
        # Step 5: Network identity — Group A (always writable in PSN mode).
        # ------------------------------------------------------------------
        print(f"\n=== Step 5: Network identity Group A — port mode + encapsulation ===")
        net_ok = True
        for oid, value in NET_GROUP_A.items():
            result = await write_and_verify(device, PSN_GEN_MIB, oid, value, PORT_INDEX)
            net_ok = net_ok and result

        # ------------------------------------------------------------------
        # Step 6: Network identity — Group B (VLAN fields, encap-dependent).
        # ------------------------------------------------------------------
        print(f"\n=== Step 6: Network identity Group B — VLAN fields (conditional) ===")

        encap_now = await device.get(PSN_GEN_MIB, 'psnGenModeEncapsulationLocal', PORT_INDEX)
        encap_val = int(encap_now) if encap_now is not None else -1

        if encap_val in (ENCAP_VLAN, ENCAP_QINQ):
            print(f"  Encapsulation = {encap_val} (tagged) → writing CVID and CoS")
            for oid, value in [('psnGenModeCvidLocal', NET_CVID_VALUE),
                                ('psnGenModeCpcpLocal', NET_CPCP_VALUE)]:
                result = await write_and_verify(device, PSN_GEN_MIB, oid, value, PORT_INDEX)
                net_ok = net_ok and result
        else:
            print(f"  Encapsulation = {encap_val} (untagged) → skipping CVID / CoS "
                  f"(only applicable for vlan(1) or qinq(2))")

        # ------------------------------------------------------------------
        # Step 7: Network identity — Group C (IP stack, ipEndpoint only).
        # These OIDs return noAccess when psnGenMode = ethEndpoint(1) or
        # l1Endpoint(0). Only attempt when psnGenMode = ipEndpoint(2).
        # ------------------------------------------------------------------
        print(f"\n=== Step 7: Network identity Group C — IP stack (ipEndpoint only) ===")

        if psn_gen_mode == PSN_MODE_IPENDPOINT:
            print(f"  psnGenMode = ipEndpoint → writing DHCP and IP profile")
            for oid, value in NET_GROUP_C.items():
                result = await write_and_verify(device, PSN_GEN_MIB, oid, value, PORT_INDEX)
                net_ok = net_ok and result
        else:
            print(f"  psnGenMode = {gen_mode_label} → skipping DHCP / IP fields.")
            print(f"  To configure IP: switch to FunctionType.PSN_IP_ENDPOINT first,")
            print(f"  which sets psnGenMode = ipEndpoint(2).")

        print(f"\n  Network identity overall: {'OK' if net_ok else 'PARTIAL FAILURE'}")

        # ------------------------------------------------------------------
        # Step 8: Restore original values.
        # ------------------------------------------------------------------
        print(f"\n=== Step 8: Restoring original configuration ===")

        # Physical restore — same conditional guards apply
        orig_connector = orig_phy.get('psnPortCfgPhyConnector')
        orig_autoneg   = orig_phy.get('psnPortCfgPhyAutonegotiationOn')

        for oid in list(PHY_PHASE_A.keys()):
            val = orig_phy.get(oid)
            if val is not None:
                await device.set(PSN_PORT_MIB, oid, int(val), PORT_INDEX)

        if orig_connector is not None and int(orig_connector) == CONNECTOR_SFP:
            val = orig_phy.get('psnPortCfgPhyLaserOn')
            if val is not None:
                await device.set(PSN_PORT_MIB, 'psnPortCfgPhyLaserOn', int(val), PORT_INDEX)

        if orig_autoneg is not None and int(orig_autoneg) == FALSE:
            val = orig_phy.get('psnPortCfgPhyForcedBitRate')
            if val is not None:
                await device.set(PSN_PORT_MIB, 'psnPortCfgPhyForcedBitRate', int(val), PORT_INDEX)

        # Network restore
        for oid in list(NET_GROUP_A.keys()):
            val = orig_net.get(oid)
            if val is not None:
                await device.set(PSN_GEN_MIB, oid, int(val), PORT_INDEX)

        orig_encap = orig_net.get('psnGenModeEncapsulationLocal')
        if orig_encap is not None and int(orig_encap) in (ENCAP_VLAN, ENCAP_QINQ):
            for oid in ('psnGenModeCvidLocal', 'psnGenModeCpcpLocal'):
                val = orig_net.get(oid)
                if val is not None:
                    await device.set(PSN_GEN_MIB, oid, int(val), PORT_INDEX)

        if psn_gen_mode == PSN_MODE_IPENDPOINT:
            for oid in list(NET_GROUP_C.keys()):
                val = orig_net.get(oid)
                if val is None:
                    continue
                # IP OIDs snapshot as raw OctetString bytes from the device.
                # Re-wrap as OctetString so the agent receives the correct
                # 4-byte binary encoding on restore.
                if len(bytes(val)) == 4:
                    await device.set(PSN_GEN_MIB, oid, OctetString(bytes(val)), PORT_INDEX)
                else:
                    await device.set(PSN_GEN_MIB, oid, int(val), PORT_INDEX)

        print("  Restore complete.")


if __name__ == '__main__':
    asyncio.run(main())