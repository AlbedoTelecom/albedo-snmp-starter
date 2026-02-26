#!/usr/bin/env python3
"""
Example 01 — Device Info
========================
Demonstrates the two basic patterns for reading a single OID:

  - quick_get()  : one-liner for a single value, handles setup and cleanup automatically.
  - SNMPDevice   : context manager for multiple reads in one session.

Reads standard SNMPv2-MIB scalars that are available on any SNMP-enabled device.

Usage:
    python ex01_device_info.py <device_ip>
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_snmp_core import SNMPDevice, quick_get


DEVICE_IP = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.100'


async def main():

    # ------------------------------------------------------------------
    # Pattern A: quick_get — simplest possible read, one value, one call.
    # Creates a device internally, reads, then cleans up automatically.
    # Use this for one-off checks in scripts.
    # ------------------------------------------------------------------
    print("=== Pattern A: quick_get ===")

    description = await quick_get(DEVICE_IP, 'SNMPv2-MIB', 'sysDescr', 0)
    print(f"Device description : {description}")

    # ------------------------------------------------------------------
    # Pattern B: SNMPDevice context manager — multiple reads in one session.
    # A single SnmpEngine and UDP socket are shared across all operations.
    # Always use 'async with' or call cleanup() manually to avoid socket leaks.
    # ------------------------------------------------------------------
    print("\n=== Pattern B: context manager ===")

    async with SNMPDevice(DEVICE_IP) as device:
        name     = await device.get('ATSL-SYSTEM-MIB', 'sysIDproduct',     0)
        serial   = await device.get('ATSL-SYSTEM-MIB', 'sysIDserialNumber',   0)
        release  = await device.get('ATSL-SYSTEM-MIB', 'sysIDswVersion',  0)
        uptime   = await device.get('SNMPv2-MIB', 'sysUpTime',   0)

        print(f"Name     : {name}")
        print(f"Serial   : {serial}")
        print(f"Release  : {release}")
        print(f"Uptime   : {uptime} (hundredths of a second)")

    # ------------------------------------------------------------------
    # Pattern C: manual cleanup — equivalent to the context manager but
    # explicit. Useful when the device lifetime spans multiple functions.
    # ------------------------------------------------------------------
    print("\n=== Pattern C: manual cleanup ===")

    device = SNMPDevice(DEVICE_IP)
    try:
        description = await device.get('SNMPv2-MIB', 'sysDescr', 0)
        print(f"Device description : {description}")
    finally:
        await device.cleanup()  # Always call this, even on error


if __name__ == '__main__':
    asyncio.run(main())
