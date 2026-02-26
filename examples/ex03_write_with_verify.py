#!/usr/bin/env python3
"""
Example 03 — Write with Verification
=====================================
Demonstrates the correct pattern for SNMP SET operations:

  1. Read the current value.
  2. Write the new value.
  3. Poll with a retry loop until the device applies it (devices apply
     configuration asynchronously — an immediate read-back may still
     return the old value).
  4. Restore the original value when done.

The retry loop is important: a single read-back immediately after SET
will often fail on ALBEDO devices even when the write was accepted.

Usage:
    python ex03_write_with_verify.py <device_ip>

Warning:
    This script toggles tdmMonEnable and restores it.  Run only when the
    device is not in an active test session.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_snmp_core import SNMPDevice

DEVICE_IP  = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.100'
TRUTH_VALUE = {1: 'true (enabled)', 2: 'false (disabled)'}  # TruthValue encoding used by ALBEDO MIBs (from SNMPv2-TC)
MIB        = 'ATSL-TDM-MONITOR-MIB'
OID        = 'tdmMonEnable'
VERIFY_TIMEOUT = 5.0   # seconds to wait for value to propagate
VERIFY_INTERVAL = 0.1  # seconds between retries


async def write_with_verify(device: SNMPDevice, mib: str, oid: str,
                             new_value: int, index: int = 0) -> bool:
    """
    Write a value and poll until the device reflects it.

    Returns True if the write was verified within VERIFY_TIMEOUT seconds.
    """
    success = await device.set(mib, oid, new_value, index)
    if not success:
        print(f"  SET rejected by device")
        return False

    # Poll until the device applies the change
    deadline = asyncio.get_event_loop().time() + VERIFY_TIMEOUT
    while asyncio.get_event_loop().time() < deadline:
        verified = await device.get(mib, oid, index)
        if verified is not None and int(verified) == new_value:
            return True
        await asyncio.sleep(VERIFY_INTERVAL)

    print(f"  Verification timed out after {VERIFY_TIMEOUT}s")
    return False


async def main():

    async with SNMPDevice(DEVICE_IP) as device:

        # Step 1: Read current value
        original = await device.get(MIB, OID, 0)
        if original is None:
            print("Could not read OID — device may not support TDM monitoring.")
            return

        print(f"Current value ({OID}): {TRUTH_VALUE[int(original)]}")

        # Step 2: Toggle (TruthValue: 1=true, 2=false)
        new_value = 2 if int(original) == 1 else 1
        print(f"Writing value ({OID}): {new_value}")

        ok = await write_with_verify(device, MIB, OID, new_value)

        if ok:
            print(f"✓ Write verified successfully")
        else:
            print(f"✗ Write could not be verified")

        # Step 3: Restore original value
        print(f"Restoring ({OID}): {int(original)}")
        restored = await write_with_verify(device, MIB, OID, int(original))
        if restored:
            print("✓ Original value restored")
        else:
            print("✗ Could not restore original value — check device manually")


if __name__ == '__main__':
    asyncio.run(main())
