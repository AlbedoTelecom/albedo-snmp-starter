#!/usr/bin/env python3
"""
Example 04 — Table Walk
========================
Demonstrates device.walk() for reading SNMP tables.

walk() issues repeated GETNEXT requests starting from the given OID and
stops when the subtree ends or the MIB boundary is reached.  The result
is a list of (oid_string, value) tuples covering all columns and rows.

Two walks are shown:
  - ATSL-SYSTEM-MIB::atslSystem   : device identity subtree, always available.
  - ATSL-TDM-MONITOR-MIB::tdmMonLineTable : ALBEDO table, populated only
    when TDM port blocks are configured on the device.

Usage:
    python ex04_walk_table.py <device_ip>
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_snmp_core import SNMPDevice, print_walk_readable, _get_mib_manager


DEVICE_IP = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.100'

async def main():

    async with SNMPDevice(DEVICE_IP) as device:

        # ------------------------------------------------------------------
        # Walk 1: standard SNMPv2-MIB system subtree.
        # Covers sysDescr, sysObjectID, sysUpTime, sysContact, sysName,
        # sysLocation, sysServices — always 7 entries.
        # ------------------------------------------------------------------
        print("=== Walk: ATSL-SYSTEM-MIB::atslSystem ===")
        results = await device.walk_readable('ATSL-SYSTEM-MIB', 'atslSystem')
        print(f"Entries found: {len(results)}")
        print_walk_readable(results)

        print()

        # ------------------------------------------------------------------
        # Walk 2: ALBEDO TDM line table.
        # Each row corresponds to one configured TDM port block and contains
        # block name, signal level, frequency, deviation, and status.
        # The table is empty if no TDM port blocks have been configured.
        # ------------------------------------------------------------------
        print("=== Walk: ATSL-TDM-MONITOR-MIB::tdmMonLineTable ===")
        results = await device.walk_readable('ATSL-TDM-MONITOR-MIB', 'tdmMonLineTable')
        print(f"Entries found: {len(results)}")
        print_walk_readable(results)

        print()

        # ------------------------------------------------------------------
        # Walk 3: ALBEDO TDM performance table.
        # Each row corresponds to one configured monitoring block and contains
        # ES, SES, UAS, BBE counters for near and far end.
        # ------------------------------------------------------------------
        print("=== Walk: ATSL-TDM-MONITOR-MIB::tdmMonPerfTable ===")
        results = await device.walk('ATSL-TDM-MONITOR-MIB', 'tdmMonPerfTable')
        print(f"Entries found: {len(results)}")
        print_walk_readable(results)


if __name__ == '__main__':
    asyncio.run(main())
