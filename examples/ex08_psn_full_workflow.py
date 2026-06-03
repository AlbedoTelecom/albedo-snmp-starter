#!/usr/bin/env python3
"""
Example 08 — PSN Full Workflow: Port Configuration + Measurement
================================================================
Combines port configuration (formerly ex09) with live measurement (formerly
ex08) into a single end-to-end script.  The workflow is:

  Phase 1 — SETUP
    1. Ensure a PSN function is active (switch from TDM/CLKMON if necessary).
    2. Read the psnGenMode scalar — needed to gate IP-level writes.
    3. Snapshot the current port config for restore at the end.

  Phase 2 — CONFIGURATION  (ATSL-PSN-PORT-MIB + ATSL-PSN-GENERATOR-MIB)
    4. Physical layer Phase A: connector, autoneg, allowed speeds, clock role.
    5. Physical layer Phase B: laser and forced bit-rate (conditionally writable).
    6. Network identity Group A: port mode, encapsulation.
    7. Network identity Group B: VLAN ID + CoS (only when encap ≠ untagged).
    8. Network identity Group C: DHCP + static IP (only when psnGenMode = ipEndpoint).

  Phase 3 — GENERATOR SETUP  (ATSL-PSN-GENERATOR-MIB)
    9.  Set Ethernet frame size and destination MAC address.
   10.  Set bandwidth profile: continuous generation at GEN_BIT_RATE.

  Phase 4 — MEASUREMENT  (ATSL-PSN-GENERATOR-MIB + ATSL-PSN-MONITOR-MIB)
   11.  Check link status on all ports.
   12.  Start generation (psnGenEnable = true) then monitoring (psnMonEnable = true).
   13.  Poll metrics at SAMPLE_INTERVAL intervals for DURATION seconds.
   14.  Stop monitoring (psnMonEnable = false) and generation (psnGenEnable = false).
   15.  Print final session summary.

  Phase 5 — CLEANUP
   16.  Restore original port configuration (runs unconditionally via try/finally).

Metrics logged per sample:
  - psnMonRateStatsTable : frame rate, bit rate, % utilisation (current, min, max)
  - psnMonSlaStatsTable  : FTD (mean), FDV (mean), lost frames, FLR
  - psnMonErrorStatsTable: FCS errors, undersized frames, oversized frames

Final summary reads:
  - psnMonStatsTable     : total frames and bytes for the session
  - psnMonEthStatsTable  : unicast / multicast / broadcast / VLAN breakdown
  - psnMonIpStatsTable   : IPv4 / IPv6 / UDP / ICMP counts

CONDITIONAL-ACCESS RULES (enforced by the agent, not by MIB syntax):
  ┌──────────────────────────────────────────────────────┬──────────────────────────────┐
  │ OID                                                  │ Writable only when           │
  ├──────────────────────────────────────────────────────┼──────────────────────────────┤
  │ psnPortCfgPhyLaserOn                                 │ connector = SFP              │
  │ psnPortCfgPhyForcedBitRate                           │ autoneg = OFF                │
  │ psnPortCfgPhy1000/100/10Allowed, psnPortCfgPhyClockRole│ autoneg = ON               │
  │ psnGenModeCvidLocal / psnGenModeCpcpLocal            │ encapsulation ≠ untagged(0)  │
  │ psnGenModeDhcpEnabled / psnGenModeIpv4*              │ psnGenMode = ipEndpoint(2)   │
  │ psnGenEthTable / psnGenBandwidthTable (most columns) │ psnGenEnable = false         │
  └──────────────────────────────────────────────────────┴──────────────────────────────┘

TOPOLOGY REQUIREMENT — LOOPBACK:
  This script generates Ethernet frames and measures the returned traffic.
  It requires port A1 to be connected to a device configured to loop all
  received frames back to the sender without inspecting the payload.

  The destination MAC is set to GEN_DST_MAC (default: 00:00:00:00:00:00).
  A loopback device echoes every frame regardless of MAC destination, so
  all-zeros is accepted.  Do NOT connect this port to a live network segment:
  the all-zeros destination MAC may be interpreted as malformed by production
  switches and the generated traffic will congest the link.

Usage:
    python ex08_psn_full_workflow.py <device_ip> [port_index] [duration_seconds]

    port_index       defaults to 1
    duration_seconds defaults to 30

Warning:
    This script modifies port parameters and starts traffic generation.
    Do not run while a test is in progress.  All modified port values are
    restored at the end, including when the script is interrupted by an
    exception.  Traffic generation is also stopped unconditionally in cleanup.
"""

import asyncio
import socket
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_snmp_core import MultifunctionDevice, FunctionType, LINK_STATUS
from pysnmp.proto.rfc1902 import OctetString, Integer

# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------
DEVICE_IP   = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.100'
PORT_INDEX  = int(sys.argv[2]) if len(sys.argv) > 2 else 1
DURATION    = int(sys.argv[3]) if len(sys.argv) > 3 else 30

# Flow index within the generator tables (psnGenEthTable, psnGenBandwidthTable).
# Rows 1–8 correspond to port A flows, rows 9–16 to port B flows.
# For a single-flow test on port A, FLOW_INDEX = PORT_INDEX = 1.
FLOW_INDEX  = PORT_INDEX

SAMPLE_INTERVAL = 5   # seconds between metric reads during measurement

# ---------------------------------------------------------------------------
# MIB names
# ---------------------------------------------------------------------------
PSN_PORT_MIB = 'ATSL-PSN-PORT-MIB'
PSN_GEN_MIB  = 'ATSL-PSN-GENERATOR-MIB'
PSN_MON_MIB  = 'ATSL-PSN-MONITOR-MIB'

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRUE  = 1   # TruthValue::true  / enabled / on
FALSE = 2   # TruthValue::false / disabled / off

CONNECTOR_RJ45 = 0
CONNECTOR_SFP  = 1

ENCAP_UNTAGGED = 0
ENCAP_VLAN     = 1
ENCAP_QINQ     = 2

PSN_MODE_L1ENDPOINT  = 0
PSN_MODE_ETHENDPOINT = 1
PSN_MODE_IPENDPOINT  = 2

PSN_FUNCTIONS = {
    FunctionType.PSN_ETH_ENDPOINT,
    FunctionType.PSN_EXTERNAL,
}

# ---------------------------------------------------------------------------
# Port configuration — edit these to match your test scenario.
# ---------------------------------------------------------------------------

# Physical layer Phase A: always writable.
PHY_PHASE_A = {
    'psnPortCfgPhyConnector':         CONNECTOR_RJ45,  # 0=RJ-45, 1=SFP
    'psnPortCfgPhyAutonegotiationOn': TRUE,             # 1=ON, 2=OFF
    'psnPortCfgPhy1000Allowed':       TRUE,
    'psnPortCfgPhy100Allowed':        TRUE,
    'psnPortCfgPhy10Allowed':         FALSE,            # disallow 10 Mb/s
    'psnPortCfgPhyClockRole':         0,                # 0=auto, 1=master, 2=slave
}

# Physical layer Phase B: conditionally writable.
PHY_LASER_VALUE       = FALSE   # sent only when connector = SFP
PHY_FORCED_RATE_VALUE = 2       # 0=10M, 1=100M, 2=1G, 3=10G — sent only when autoneg = OFF

# Network identity Group A: always writable in PSN mode.
NET_GROUP_A = {
    'psnGenModePort':               1,              # 1=txrx
    'psnGenModeEncapsulationLocal': ENCAP_UNTAGGED, # 0=untagged, 1=vlan, 2=qinq
}

# Network identity Group B: sent only when encapsulation ≠ untagged.
NET_CVID_VALUE = 100   # VLAN ID
NET_CPCP_VALUE = 0     # 3-bit CoS field

# Network identity Group C: sent only when psnGenMode = ipEndpoint(2).
#
# InetAddressIPv4 encoding note:
#   InetAddressIPv4 is OCTET STRING (SIZE 4) — four raw bytes in network byte
#   order, NOT a dotted-decimal ASCII string.  Passing a plain Python string
#   wraps it as 12 ASCII bytes, corrupting the agent's stored value.
#   Always use ip_to_snmp() before calling device.set().
NET_GROUP_C = {
    'psnGenModeDhcpEnabled':        FALSE,
    'psnGenModeIpv4AddressStatic':  None,   # filled by ip_to_snmp() below
    'psnGenModeIpv4MaskStatic':     None,
    'psnGenModeIpv4GatewayStatic':  None,
}

# ---------------------------------------------------------------------------
# Generator configuration — 256 kbps constant Ethernet stream, 64-byte frames.
# See TOPOLOGY REQUIREMENT in the module docstring before changing GEN_DST_MAC.
# ---------------------------------------------------------------------------

GEN_FRAME_SIZE  = 64
# Total Ethernet frame in bytes including destination MAC, source MAC,
# type/length, payload, and 4-byte FCS.  Minimum valid frame is 64 bytes.

GEN_BIT_RATE    = 256
# psnGenBandwidthBitRate value.  Real32 TC encoding: Mbps × 1000.
# 256 kbps = 0.256 Mbps → 0.256 × 1000 = 256.

GEN_DST_MAC     = OctetString(b'\x00\x00\x00\x00\x00\x00')
# Destination MAC address (MacAddress = OCTET STRING SIZE 6).
# All-zeros is used because the loopback peer echoes every received frame
# regardless of its MAC destination.  Change this if your loopback device
# requires a specific address.

GEN_DST_MAC_ORIGIN_MANUAL = 0   # psnGenEthMacDstAddressOrigin: manual(0)
GEN_BW_MODE_CONTINUOUS    = 1   # psnGenBandwidthMode: continuous(1)
# GEN_BW_MODE_DISABLED      = 0   # psnGenBandwidthMode: disabled(0)


# ---------------------------------------------------------------------------
# IPv4 encoding helpers
# ---------------------------------------------------------------------------
def ip_to_snmp(dotted: str) -> OctetString:
    """Encode a dotted-decimal IPv4 string as a 4-byte SNMP OctetString."""
    return OctetString(socket.inet_aton(dotted))


def snmp_to_ip(val) -> str:
    """Decode a 4-byte SNMP OctetString to dotted-decimal."""
    return socket.inet_ntoa(bytes(val))


# Populate the OctetString values after defining the helpers.
NET_GROUP_C['psnGenModeIpv4AddressStatic'] = ip_to_snmp('192.168.10.1')
NET_GROUP_C['psnGenModeIpv4MaskStatic']    = ip_to_snmp('255.255.255.0')
NET_GROUP_C['psnGenModeIpv4GatewayStatic'] = ip_to_snmp('192.168.10.254')


# ---------------------------------------------------------------------------
# Helper: write a single OID and poll until the device confirms the new value.
# ---------------------------------------------------------------------------
async def write_and_verify(device, mib: str, oid: str, value,
                            index: int, timeout: float = 5.0) -> bool:
    """Set an OID and poll until the readback matches the written value.

    Handles three value types:
      - OctetString (InetAddressIPv4, MacAddress): compared as raw bytes
      - int-coercible (TruthValue, enumerations): compared as int
      - str fallback for anything else
    """
    ok = await device.set(mib, oid, value, index)
    if not ok:
        print(f"    ✗ SET rejected: {oid} = {value}")
        return False

    deadline = asyncio.get_event_loop().time() + timeout
    readback  = None
    while asyncio.get_event_loop().time() < deadline:
        readback = await device.get(mib, oid, index)
        if readback is not None:
            if isinstance(value, OctetString):
                match   = bytes(readback) == bytes(value)
                if len(bytes(value)) == 4:
                    display = snmp_to_ip(value)
                elif len(bytes(value)) == 6:
                    display = ':'.join(f'{b:02x}' for b in bytes(value))
                else:
                    display = repr(bytes(value))
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


# ---------------------------------------------------------------------------
# Helper: snapshot writable OIDs for restore.
# ---------------------------------------------------------------------------
async def snapshot_phy(device, index: int) -> dict:
    """Read all writable physical-layer OIDs."""
    oids = list(PHY_PHASE_A.keys()) + ['psnPortCfgPhyLaserOn', 'psnPortCfgPhyForcedBitRate']
    return {oid: await device.get(PSN_PORT_MIB, oid, index) for oid in oids}


async def snapshot_net(device, index: int) -> dict:
    """Read all writable network-identity OIDs."""
    oids = (
        list(NET_GROUP_A.keys()) +
        ['psnGenModeCvidLocal', 'psnGenModeCpcpLocal'] +
        list(NET_GROUP_C.keys())
    )
    return {oid: await device.get(PSN_GEN_MIB, oid, index) for oid in oids}


# ---------------------------------------------------------------------------
# Phase 4 helpers: measurement
# ---------------------------------------------------------------------------
async def check_link_status(device):
    """Print current link status for all PSN ports."""
    print("\n--- Link Status ---")
    rows = await device.walk(PSN_MON_MIB, 'psnLinkStatusTable')

    names  = {}
    values = {}
    for oid_str, value in rows:
        parts = oid_str.split('.')
        try:
            col = int(parts[-2])
            row = int(parts[-1])
            if col == 2:
                names[row]  = str(value)
            elif col == 3:
                values[row] = int(value)
        except (ValueError, IndexError):
            continue

    if not names:
        print("  (no link status entries)")
        return

    for row in sorted(names):
        name   = names.get(row, f'port{row}')
        status = LINK_STATUS.get(values.get(row, 4), 'unknown')
        print(f"  {name}: {status}")


async def sample_metrics(device, sample_num: int):
    """Read and print rate, SLA and error stats for monitoring block 1."""
    print(f"\n  [Sample {sample_num}]")

    # Rate stats — psnMonRateStatsTable columns for row 1:
    #   3=fps  4=EthBps  5=EthPercent(×1000)  7=EthMinBps  10=EthMaxBps
    rate_rows = await device.walk(PSN_MON_MIB, 'psnMonRateStatsTable')
    rate = {}
    for oid_str, value in rate_rows:
        parts = oid_str.split('.')
        try:
            col = int(parts[-2])
            row = int(parts[-1])
            if row == 1:
                rate[col] = int(value)
        except (ValueError, IndexError):
            continue

    if rate:
        fps     = rate.get(3,  0)
        bps     = rate.get(4,  0)
        pct     = rate.get(5,  0) / 1000.0   # RatioPercentage is ×1000
        min_bps = rate.get(7,  0)
        max_bps = rate.get(10, 0)
        print(f"    Rate     : {fps} fps  |  {bps:,} bps  |  {pct:.2f}%")
        print(f"    Min/Max  : {min_bps:,} / {max_bps:,} bps")

    # SLA stats — psnMonSlaStatsTable columns for row 1:
    #   6=FtdMean(µs)  11=FdvMean(µs)  14=Lost  15=Flr(×1000)
    sla_rows = await device.walk(PSN_MON_MIB, 'psnMonSlaStatsTable')
    sla = {}
    for oid_str, value in sla_rows:
        parts = oid_str.split('.')
        try:
            col = int(parts[-2])
            row = int(parts[-1])
            if row == 1:
                sla[col] = int(value)
        except (ValueError, IndexError):
            continue

    if sla:
        ftd_mean = sla.get(6,  0)           # µs
        fdv_mean = sla.get(11, 0)           # µs
        lost     = sla.get(14, 0)
        flr      = sla.get(15, 0) / 1000.0  # RatioPercentage
        print(f"    FTD mean : {ftd_mean} µs")
        print(f"    FDV mean : {fdv_mean} µs")
        print(f"    Lost     : {lost} frames  |  FLR: {flr:.3f}%")

    # Error stats — psnMonErrorStatsTable columns for row 1:
    #   3=UnderS  6=OverS  19=FCS
    err_rows = await device.walk(PSN_MON_MIB, 'psnMonErrorStatsTable')
    err = {}
    for oid_str, value in err_rows:
        parts = oid_str.split('.')
        try:
            col = int(parts[-2])
            row = int(parts[-1])
            if row == 1:
                err[col] = int(value)
        except (ValueError, IndexError):
            continue

    if err:
        under = err.get(3,  0)
        over  = err.get(6,  0)
        fcs   = err.get(19, 0)
        print(f"    FCS err  : {fcs}  |  Undersized: {under}  |  Oversized: {over}")


async def print_summary(device):
    """Print totals for the completed measurement session."""
    print("\n=== Final Summary ===")

    # General stats — psnMonStatsTable columns for row 1:
    #   3=frames  4=bytes
    stats_rows = await device.walk(PSN_MON_MIB, 'psnMonStatsTable')
    stats = {}
    for oid_str, value in stats_rows:
        parts = oid_str.split('.')
        try:
            col = int(parts[-2])
            row = int(parts[-1])
            if row == 1:
                stats[col] = int(value)
        except (ValueError, IndexError):
            continue

    if stats:
        print(f"  Total frames : {stats.get(3, 0):,}")
        print(f"  Total bytes  : {stats.get(4, 0):,}")

    # Ethernet breakdown — psnMonEthStatsTable columns for row 1:
    #   3=unicast  4=multicast  5=broadcast  6=vlan
    eth_rows = await device.walk(PSN_MON_MIB, 'psnMonEthStatsTable')
    eth = {}
    for oid_str, value in eth_rows:
        parts = oid_str.split('.')
        try:
            col = int(parts[-2])
            row = int(parts[-1])
            if row == 1:
                eth[col] = int(value)
        except (ValueError, IndexError):
            continue

    if eth:
        print(f"  Unicast      : {eth.get(3, 0):,} frames")
        print(f"  Multicast    : {eth.get(4, 0):,} frames")
        print(f"  Broadcast    : {eth.get(5, 0):,} frames")
        print(f"  VLAN-tagged  : {eth.get(6, 0):,} frames")

    # IP breakdown — psnMonIpStatsTable columns for row 1:
    #   3=ipv4  5=ipv6  10=udp  12=icmp
    ip_rows = await device.walk(PSN_MON_MIB, 'psnMonIpStatsTable')
    ip = {}
    for oid_str, value in ip_rows:
        parts = oid_str.split('.')
        try:
            col = int(parts[-2])
            row = int(parts[-1])
            if row == 1:
                ip[col] = int(value)
        except (ValueError, IndexError):
            continue

    if ip:
        print(f"  IPv4 packets : {ip.get(3,  0):,}")
        print(f"  IPv6 packets : {ip.get(5,  0):,}")
        print(f"  UDP packets  : {ip.get(10, 0):,}")
        print(f"  ICMP packets : {ip.get(12, 0):,}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():

    print("=" * 60)
    print("PSN FULL WORKFLOW: PORT CONFIG + MEASUREMENT")
    print("=" * 60)
    print(f"Device     : {DEVICE_IP}")
    print(f"Port index : {PORT_INDEX}")
    print(f"Duration   : {DURATION}s  (sample every {SAMPLE_INTERVAL}s)")
    print(f"Generator  : {GEN_BIT_RATE / 1000:.3f} Mbps  |  {GEN_FRAME_SIZE}-byte frames  |  flow {FLOW_INDEX}")
    print(f"Started    : {datetime.now().strftime('%H:%M:%S')}")

    async with MultifunctionDevice(DEVICE_IP) as device:

        # ------------------------------------------------------------------
        # Step 1: Ensure a PSN function is active.
        # ------------------------------------------------------------------
        print("\n=== Step 1: Checking / switching function mode ===")
        if await device.is_multifunction():
            active = await device.get_active_function()
            if active not in PSN_FUNCTIONS:
                # Device is in TDM or CLKMON — switch to Eth Endpoint as the
                # safe landing mode.  If already in any PSN sub-mode (including
                # PSN_IP_ENDPOINT) leave it alone so Group-C OIDs are accessible.
                ok = await device.ensure_function(FunctionType.PSN_ETH_ENDPOINT)
                if not ok:
                    print("  ERROR: Could not switch to PSN mode — aborting.")
                    return
                active = await device.get_active_function()
            print(f"  Active function: {active.name if active else 'unknown'}")
        else:
            print("  Non-multifunction device — assuming PSN mode is active.")

        # Read the psnGenMode scalar.  This gates Group-C writes AND provides
        # a human-readable label for all subsequent output.
        psn_gen_mode_raw = await device.get(PSN_GEN_MIB, 'psnGenMode', 0)
        psn_gen_mode     = int(psn_gen_mode_raw) if psn_gen_mode_raw is not None else -1
        gen_mode_label   = {
            PSN_MODE_L1ENDPOINT:  'l1Endpoint',
            PSN_MODE_ETHENDPOINT: 'ethEndpoint',
            PSN_MODE_IPENDPOINT:  'ipEndpoint',
        }.get(psn_gen_mode, f'unknown({psn_gen_mode})')
        print(f"  psnGenMode = {psn_gen_mode} ({gen_mode_label})")

        # ------------------------------------------------------------------
        # Step 2: Snapshot current config (for restore at the end).
        # ------------------------------------------------------------------
        print(f"\n=== Step 2: Snapshot current config (port {PORT_INDEX}) ===")
        orig_phy = await snapshot_phy(device, PORT_INDEX)
        orig_net = await snapshot_net(device, PORT_INDEX)
        for oid, val in {**orig_phy, **orig_net}.items():
            print(f"  {oid:42s} = {val}")

        # Wrap all config + measurement in try/finally so the restore always runs.
        try:

            # --------------------------------------------------------------
            # Step 3: Physical layer Phase A — always writable.
            # --------------------------------------------------------------
            print(f"\n=== Step 3: Physical config Phase A — connector + autoneg ===")
            phy_ok = True
            for oid, value in PHY_PHASE_A.items():
                result  = await write_and_verify(device, PSN_PORT_MIB, oid, value, PORT_INDEX)
                phy_ok  = phy_ok and result

            # --------------------------------------------------------------
            # Step 4: Physical layer Phase B — conditionally writable.
            # Read post-Phase-A state before deciding which OIDs to send.
            # --------------------------------------------------------------
            print(f"\n=== Step 4: Physical config Phase B — conditional OIDs ===")

            connector_now = await device.get(PSN_PORT_MIB, 'psnPortCfgPhyConnector',         PORT_INDEX)
            autoneg_now   = await device.get(PSN_PORT_MIB, 'psnPortCfgPhyAutonegotiationOn', PORT_INDEX)
            connector_val = int(connector_now) if connector_now is not None else -1
            autoneg_val   = int(autoneg_now)   if autoneg_now   is not None else -1

            if connector_val == CONNECTOR_SFP:
                print(f"  Connector = SFP → writing psnPortCfgPhyLaserOn = {PHY_LASER_VALUE}")
                result  = await write_and_verify(device, PSN_PORT_MIB, 'psnPortCfgPhyLaserOn',
                                                  PHY_LASER_VALUE, PORT_INDEX)
                phy_ok  = phy_ok and result
            else:
                print("  Connector = RJ-45 → skipping psnPortCfgPhyLaserOn (SFP only)")

            if autoneg_val == FALSE:
                print(f"  Autoneg = OFF → writing psnPortCfgPhyForcedBitRate = {PHY_FORCED_RATE_VALUE}")
                result  = await write_and_verify(device, PSN_PORT_MIB, 'psnPortCfgPhyForcedBitRate',
                                                  PHY_FORCED_RATE_VALUE, PORT_INDEX)
                phy_ok  = phy_ok and result
            else:
                print("  Autoneg = ON → skipping psnPortCfgPhyForcedBitRate (used only when autoneg is OFF)")

            print(f"\n  Physical config: {'OK' if phy_ok else 'PARTIAL FAILURE'}")

            # --------------------------------------------------------------
            # Step 5: Network identity Group A — always writable in PSN mode.
            # --------------------------------------------------------------
            print(f"\n=== Step 5: Network identity Group A — port mode + encapsulation ===")
            net_ok = True
            for oid, value in NET_GROUP_A.items():
                result  = await write_and_verify(device, PSN_GEN_MIB, oid, value, PORT_INDEX)
                net_ok  = net_ok and result

            # --------------------------------------------------------------
            # Step 6: Network identity Group B — VLAN fields (encap-dependent).
            # Read post-Group-A encapsulation before deciding.
            # --------------------------------------------------------------
            print(f"\n=== Step 6: Network identity Group B — VLAN fields (conditional) ===")

            encap_now = await device.get(PSN_GEN_MIB, 'psnGenModeEncapsulationLocal', PORT_INDEX)
            encap_val = int(encap_now) if encap_now is not None else -1

            if encap_val in (ENCAP_VLAN, ENCAP_QINQ):
                print(f"  Encapsulation = {encap_val} (tagged) → writing CVID and CoS")
                for oid, value in [('psnGenModeCvidLocal', NET_CVID_VALUE),
                                    ('psnGenModeCpcpLocal', NET_CPCP_VALUE)]:
                    result  = await write_and_verify(device, PSN_GEN_MIB, oid, value, PORT_INDEX)
                    net_ok  = net_ok and result
            else:
                print(f"  Encapsulation = {encap_val} (untagged) → "
                      f"skipping CVID / CoS (only for vlan(1) or qinq(2))")

            # --------------------------------------------------------------
            # Step 7: Network identity Group C — IP stack (ipEndpoint only).
            # These OIDs return noAccess when psnGenMode ≠ ipEndpoint(2).
            # --------------------------------------------------------------
            print(f"\n=== Step 7: Network identity Group C — IP stack (ipEndpoint only) ===")

            if psn_gen_mode == PSN_MODE_IPENDPOINT:
                print("  psnGenMode = ipEndpoint → writing DHCP and static IP profile")
                for oid, value in NET_GROUP_C.items():
                    result  = await write_and_verify(device, PSN_GEN_MIB, oid, value, PORT_INDEX)
                    net_ok  = net_ok and result
            else:
                print(f"  psnGenMode = {gen_mode_label} → skipping DHCP / IP fields.")
                print("  To configure IP: switch to FunctionType.PSN_IP_ENDPOINT first,")
                print("  which sets psnGenMode = ipEndpoint(2).")

            print(f"\n  Network identity: {'OK' if net_ok else 'PARTIAL FAILURE'}")

            # --------------------------------------------------------------
            # Step 8: Generator setup — frame size, destination MAC, bandwidth.
            #
            # psnGenEthTable and psnGenBandwidthTable are both indexed by
            # PORT_INDEX (same as the port config tables).
            # Most columns in these tables return noAccess while psnGenEnable
            # is true, so this step must run before generation starts.
            # --------------------------------------------------------------
            print(f"\n=== Step 8: Generator setup — frame + bandwidth ===")

            gen_ok = True

            # Ethernet frame parameters
            result = await write_and_verify(device, PSN_GEN_MIB,
                                             'psnGenEthFrameSize', GEN_FRAME_SIZE, FLOW_INDEX)
            gen_ok = gen_ok and result

            # Destination MAC — manual origin + explicit address.
            # The all-zeros address is valid for a loopback connection where
            # the peer echoes every frame regardless of MAC destination.
            result = await write_and_verify(device, PSN_GEN_MIB,
                                             'psnGenEthMacDstAddressOrigin',
                                             GEN_DST_MAC_ORIGIN_MANUAL, FLOW_INDEX)
            gen_ok = gen_ok and result

            result = await write_and_verify(device, PSN_GEN_MIB,
                                             'psnGenEthMacDstAddress', GEN_DST_MAC, FLOW_INDEX)
            gen_ok = gen_ok and result

            # Bandwidth profile — continuous at GEN_BIT_RATE.
            # psnGenBandwidthMode must be set before psnGenBandwidthBitRate
            # because some agents gate the bit-rate write on the mode being
            # something other than disabled(0).
            result = await write_and_verify(device, PSN_GEN_MIB,
                                             'psnGenBandwidthMode',
                                             GEN_BW_MODE_CONTINUOUS, FLOW_INDEX)
            gen_ok = gen_ok and result

            # psnGenBandwidthBitRate uses the Real32 textual convention:
            # SYNTAX Integer32, DISPLAY-HINT "d-3".  The integer value equals
            # the bit rate in bps multiplied by 1000 (three implied decimal places).
            # 256 kbps = 256,000 bps → write Integer32(256,000,000).
            result = await write_and_verify(device, PSN_GEN_MIB,
                                             'psnGenBandwidthBitRate',
                                             Integer(GEN_BIT_RATE), FLOW_INDEX)
            gen_ok = gen_ok and result

            print(f"\n  Generator setup: {'OK' if gen_ok else 'PARTIAL FAILURE'}")

            # ==============================================================
            # MEASUREMENT PHASE
            # ==============================================================

            # --------------------------------------------------------------
            # Step 9: Check link status before starting.
            # --------------------------------------------------------------
            await check_link_status(device)

            # --------------------------------------------------------------
            # Step 10: Start generation then monitoring.
            # Generation is started first so that the monitor counters capture
            # the full stream from the very first sample interval.
            # --------------------------------------------------------------
            print("\n--- Starting Generation and Monitoring ---")

            gen_started = await device.set(PSN_GEN_MIB, 'psnGenEnable', TRUE, 0)
            if not gen_started:
                print("Failed to enable generation — skipping measurement.")
            else:
                print("psnGenEnable = true")

                mon_started = await device.set(PSN_MON_MIB, 'psnMonEnable', TRUE, 0)
                if not mon_started:
                    print("Failed to enable monitoring — stopping generation.")
                    await device.set(PSN_GEN_MIB, 'psnGenEnable', FALSE, 0)
                else:
                    print("psnMonEnable = true")

                    # ----------------------------------------------------------
                    # Step 11: Sample loop.
                    # ----------------------------------------------------------
                    print(f"\n--- Sampling ({DURATION}s) ---")
                    elapsed    = 0
                    sample_num = 0
                    while elapsed < DURATION:
                        await asyncio.sleep(SAMPLE_INTERVAL)
                        elapsed    += SAMPLE_INTERVAL
                        sample_num += 1
                        await sample_metrics(device, sample_num)

                    # ----------------------------------------------------------
                    # Step 12: Stop monitoring then generation.
                    # Monitoring is stopped first so the final counters are stable
                    # before generation ceases.
                    # ----------------------------------------------------------
                    print("\n--- Stopping Monitoring and Generation ---")
                    await device.set(PSN_MON_MIB, 'psnMonEnable', FALSE, 0)
                    print("psnMonEnable = false")
                    await device.set(PSN_GEN_MIB, 'psnGenEnable', FALSE, 0)
                    print("psnGenEnable = false")

                    # ----------------------------------------------------------
                    # Step 13: Final summary.
                    # ----------------------------------------------------------
                    await print_summary(device)

        finally:

            # --------------------------------------------------------------
            # Step 14: Restore original configuration (always runs).
            # --------------------------------------------------------------
            print(f"\n=== Step 14: Restoring original configuration ===")

            # Stop generation and reset bandwidth mode before restoring port
            # config.  Several port config OIDs (connector, allowed speeds,
            # clock role, port mode) return noAccess while psnGenEnable = true.
            # psnMonEnable=false stops monitoring but does not stop generation —
            # it must be stopped explicitly here in case the measurement block
            # was skipped due to an earlier error.
            await device.set(PSN_GEN_MIB, 'psnGenEnable', FALSE, 0)
            # await device.set(PSN_GEN_MIB, 'psnGenBandwidthMode', GEN_BW_MODE_DISABLED, PORT_INDEX)
            await asyncio.sleep(5)

            # Physical restore — respect the same conditional guards as config.
            orig_connector = orig_phy.get('psnPortCfgPhyConnector')
            orig_autoneg   = orig_phy.get('psnPortCfgPhyAutonegotiationOn')

            # 1. Connector — always writable regardless of autoneg state.
            val = orig_phy.get('psnPortCfgPhyConnector')
            if val is not None:
                await device.set(PSN_PORT_MIB, 'psnPortCfgPhyConnector', int(val), PORT_INDEX)

            # 2. Autoneg-dependent OIDs — write while autoneg is still ON (left ON by
            #    the config phase). These return noAccess once autoneg is turned OFF.
            for oid in ('psnPortCfgPhy1000Allowed', 'psnPortCfgPhy100Allowed',
                        'psnPortCfgPhy10Allowed',   'psnPortCfgPhyClockRole'):
                val = orig_phy.get(oid)
                if val is not None:
                    await device.set(PSN_PORT_MIB, oid, int(val), PORT_INDEX)

            # 3. Autoneg itself — written after the bitmap so turning it OFF does not
            #    lock out step 2 above.
            if orig_autoneg is not None:
                await device.set(PSN_PORT_MIB, 'psnPortCfgPhyAutonegotiationOn',
                                int(orig_autoneg), PORT_INDEX)

            # 4. SFP-only conditional (unchanged).
            if orig_connector is not None and int(orig_connector) == CONNECTOR_SFP:
                val = orig_phy.get('psnPortCfgPhyLaserOn')
                if val is not None:
                    await device.set(PSN_PORT_MIB, 'psnPortCfgPhyLaserOn', int(val), PORT_INDEX)

            # 5. Autoneg-OFF-only conditional (unchanged).
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
                    # 4-byte binary encoding on restore, not an ASCII string.
                    if len(bytes(val)) == 4:
                        await device.set(PSN_GEN_MIB, oid, OctetString(bytes(val)), PORT_INDEX)
                    else:
                        await device.set(PSN_GEN_MIB, oid, int(val), PORT_INDEX)

            print("  Restore complete.")

    print(f"\nFinished : {datetime.now().strftime('%H:%M:%S')}")


if __name__ == '__main__':
    asyncio.run(main())
