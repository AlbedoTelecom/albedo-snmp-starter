#!/usr/bin/env python3
"""
Example 06 — MIB Manager
==========================
Demonstrates AlbedoMibManager directly for MIB compilation and OID resolution.

In normal usage you do not need to call the MIB manager directly — SNMPDevice
handles it internally.  This example is useful for:
  - Initial project setup (first-time MIB compilation).
  - Debugging MIB resolution issues.
  - Batch-compiling MIBs before running a test suite.
  - Translating symbolic names to numeric OIDs for logging or documentation.

Usage:
    python ex06_mib_manager.py [--force]

    --force   Recompile all MIBs even if they already exist.

Prerequisites:
    pip install pysmi
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_mib_core import AlbedoMibManager


def main():

    force = '--force' in sys.argv

    manager = AlbedoMibManager()

    # ------------------------------------------------------------------
    # Step 1: diagnose() — print the current state of MIB paths and
    # the MibBuilder search path.  Run this first if anything is broken.
    # ------------------------------------------------------------------
    print("=== MIB Manager Diagnostics ===")
    manager.diagnose()
    print()

    # ------------------------------------------------------------------
    # Step 2: compile_all_mibs() — compile all .txt files in the text
    # directory to .py files in the compiled directory.
    # Already-compiled MIBs are skipped unless force=True.
    # ------------------------------------------------------------------
    print("=== Compiling MIBs ===")
    results = manager.compile_all_mibs(force=force)
    print(f"Success : {len(results['success'])}")
    print(f"Failed  : {len(results['failed'])}")
    if results['failed']:
        print("Failed MIBs:")
        for mib in results['failed']:
            print(f"  - {mib}")
    print()

    # ------------------------------------------------------------------
    # Step 3: name_to_oid() — resolve a symbolic name to a numeric OID.
    # The MIB is loaded on demand from the compiled directory.
    # ------------------------------------------------------------------
    print("=== OID Resolution ===")
    names_to_resolve = [
        'ATSL-TDM-MONITOR-MIB::tdmMonEnable.0',
        'ATSL-TDM-MONITOR-MIB::tdmMonPerformanceStandard.0',
        'ATSL-TDM-MONITOR-MIB::tdmMonDelayEnable.0',
        'ATSL-MULTIFUNCTION-MIB::mfActiveFunc.0',
        'SNMPv2-MIB::sysDescr.0',
    ]

    for name in names_to_resolve:
        try:
            oid = manager.name_to_oid(name)
            print(f"  {name}")
            print(f"    → {oid}")
        except RuntimeError as e:
            print(f"  {name}")
            print(f"    ✗ {e}")
    print()

    # ------------------------------------------------------------------
    # Step 4: Helper codes — convenience dictionaries for common MIB
    # enumerations used in ALBEDO devices.
    # ------------------------------------------------------------------
    print("=== RowStatus Codes ===")
    for name, code in manager.get_row_status_codes().items():
        print(f"  {code} = {name}")

    print()
    print("=== Config File Action Codes ===")
    for name, code in manager.get_config_file_action_codes().items():
        print(f"  {code} = {name}")

    print()
    print("=== Config File Result Codes ===")
    for code, name in manager.get_config_file_result_codes().items():
        print(f"  {code} = {name}")


if __name__ == '__main__':
    main()
