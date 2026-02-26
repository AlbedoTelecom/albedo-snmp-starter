#!/usr/bin/env python3
"""
Example 02 — Reading ALBEDO MIBs
=================================
Demonstrates reading OIDs from ALBEDO-specific MIB modules.

The key difference from standard MIBs is that ALBEDO OIDs must first be
resolved through the compiled MIB files in src/mibs/compiled/.  The
AlbedoMibManager handles this automatically when SNMPDevice is used.

Reads from:
  - ATSL-TDM-MONITOR-MIB  : TDM monitoring control and status
  - ATSL-SYSTEM-MIB        : Device-level system info

Usage:
    python ex02_read_albedo_mibs.py <device_ip>

Note:
    Values returned for TDM OIDs require TDM mode to be active on the device.
    If the device is in PSN mode these reads will still succeed but the
    monitoring values may be at their default/idle state.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_snmp_core import SNMPDevice, TRUTH_VALUE, TDM_PERFORMANCE_STANDARDS


DEVICE_IP = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.100'

async def main():

    async with SNMPDevice(DEVICE_IP) as device:

        print("=== TDM Monitoring Control ===")

        # tdmMonEnable is a scalar (index 0), type TruthValue: 1=true, 2=false
        enabled = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 0)
        if enabled is not None:
            print(f"Monitoring enabled : {TRUTH_VALUE.get(int(enabled), enabled)}")
        else:
            print("Monitoring enabled : (not available)")

        # Performance standard currently configured
        perf_std = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonPerformanceStandard', 0)
        if perf_std is not None:
            print(f"Performance standard: {TDM_PERFORMANCE_STANDARDS.get(int(perf_std), perf_std)}")

        # Delay measurement enabled
        delay_en = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonDelayEnable', 0)
        if delay_en is not None:
            print(f"Delay measurement  : {TRUTH_VALUE.get(int(delay_en), delay_en)}")

        print()
        print("=== TDM Delay Configuration ===")

        # Delay mode (RTD or one-way depending on MIB value)
        delay_mode = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonDelayMode', 0)
        if delay_mode is not None:
            print(f"Delay mode  : {delay_mode}")

        # RTD offset in microseconds
        rtd_offset = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonDelayRtdOffset', 0)
        if rtd_offset is not None:
            print(f"RTD offset  : {rtd_offset} µs")

        # Forward offset
        fwd_offset = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonDelayForwardOffset', 0)
        if fwd_offset is not None:
            print(f"Fwd offset  : {fwd_offset} µs")


if __name__ == '__main__':
    asyncio.run(main())
