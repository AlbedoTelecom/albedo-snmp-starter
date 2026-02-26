#!/usr/bin/env python3
"""
Example 05 — Multifunction Device
===================================
Demonstrates MultifunctionDevice for devices like xGenius that can operate
in different function modes (TDM, PSN, Datacom, etc.).

Key rules for multifunction devices:
  - Always detect the active function before accessing function-specific MIBs.
  - Never read/write function-specific OIDs while a different function is active;
    the device will return inconsistent or meaningless values.
  - Use ensure_function() to switch mode safely before starting a test.
  - Mode switches stop all current test activity — do not switch mid-test.

Usage:
    python ex05_multifunction.py <device_ip>
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_snmp_core import MultifunctionDevice, FunctionType, TRUTH_VALUE, _get_mib_manager


DEVICE_IP = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.100'

def print_walk_results(results: list, max_rows: int = 20):
    """Pretty-print walk results, truncating if large."""
    mgr = _get_mib_manager()
    if not results:
        print("  (empty)")
        return
    for oid, value in results[:max_rows]:
          # Optional: convert OID to symbolic name if available
        print(f"  {mgr.oid_to_name(oid)} = {value}")
    if len(results) > max_rows:
        print(f"  ... and {len(results) - max_rows} more entries")

async def main():

    async with MultifunctionDevice(DEVICE_IP) as device:

        # ------------------------------------------------------------------
        # Step 1: Detect whether the device supports multifunction operation.
        # Non-multifunction devices (e.g. dedicated E1 testers) return False.
        # ------------------------------------------------------------------
        is_mf = await device.is_multifunction()
        print(f"Multifunction device: {is_mf}")

        if not is_mf:
            print("Device does not support multifunction — exiting.")
            return

        # ------------------------------------------------------------------
        # Step 2: Read the currently active function.
        # mfActiveFunc returns an integer mapped to FunctionType.
        # ------------------------------------------------------------------
        active = await device.get_active_function()
        print(f"Active function     : {active.name if active else 'unknown'}")

        # ------------------------------------------------------------------
        # Step 3: Walk the function table to see all available modes and their
        # current status.  Each row corresponds to one supported function.
        # ------------------------------------------------------------------
        print()
        print("=== Available functions (mfFuncTable) ===")
        func_table = await device.walk('ATSL-MULTIFUNCTION-MIB', 'mfFuncTable')
        if func_table:
            print_walk_results(func_table)
        else:
            print("  (table empty or not available)")

        # ------------------------------------------------------------------
        # Step 4: Conditional access — only read TDM OIDs if TDM is active.
        # Accessing function-specific MIBs in the wrong mode gives unreliable
        # results and may confuse the device state.
        # ------------------------------------------------------------------
        print()
        if active == FunctionType.TDM_ENDPOINT:
            print("=== TDM mode is active — reading TDM status ===")
            tdm_enabled = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 0)
            print(f"TDM monitoring enabled: {TRUTH_VALUE.get(tdm_enabled, tdm_enabled)}")

        elif active == FunctionType.PSN_ETH_ENDPOINT:
            print("=== PSN mode is active — reading PSN status ===")
            psn_enabled = await device.get('ATSL-PSN-MONITOR-MIB', 'psnMonEnable', 0)
            print(f"PSN monitoring enabled: {TRUTH_VALUE.get(psn_enabled, psn_enabled)}")

        else:
            print(f"=== Active mode is {active.name} — no specific reads configured ===")

        # ------------------------------------------------------------------
        # Step 5: ensure_function() — switch to a required mode only if
        # needed.  If the device is already in the target mode, this is a
        # no-op.  If a switch is needed, it waits for the device to settle.
        #
        # Uncomment the block below to test switching to TDM_MONITOR mode:
        # ------------------------------------------------------------------
        # print()
        # print("=== Switching to TDM_ENDPOINT mode ===")
        # ok = await device.ensure_function(FunctionType.TDM_ENDPOINT)
        # if ok:
        #     print("✓ Now in TDM_ENDPOINT mode")
        #     tdm_enabled = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 0)
        #     print(f"  tdmMonEnable = {TRUTH_VALUE.get(tdm_enabled, tdm_enabled)}")
        # else:
        #     print("✗ Could not switch to TDM_ENDPOINT mode")


if __name__ == '__main__':
    asyncio.run(main())
