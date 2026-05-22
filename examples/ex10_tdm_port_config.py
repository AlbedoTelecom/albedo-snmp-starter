#!/usr/bin/env python3
"""
Example 10 — TDM Port Configuration
======================================
Demonstrates how to configure a TDM test port in two layers:

  Layer 1 — Port mode (ATSL-TDM-PORT-MIB, tdmPortModeTable)
    - Sets the interface type per port (e.g. G.703 E1, T1, Datacom)
    - One row per physical port; index 1 = port A, index 2 = port B

  Layer 2 — BER test pattern (ATSL-TDM-PORT-MIB, tdmPortPatternTable)
    - Selects the TX and RX PRBS pattern type
    - Optional: sets a 32-bit fixed user pattern when pattern type is 'user'

IMPORTANT — MULTIFUNCTION DEVICES (xGenius):
  - Always call ensure_function(FunctionType.TDM_ENDPOINT) before writing
    TDM OIDs.  Writing TDM OIDs while PSN is active causes the agent to
    return inconsistentValue or silently discard the write.
  - tdmPortMode (the scalar, not the table) is DEPRECATED as of MIB rev
    201702010000Z — do NOT use it.  Mode selection for multifunction devices
    must be done through ATSL-MULTIFUNCTION-MIB / mfFuncTable.
  - tdmPortModeInterface in tdmPortModeTable IS still writable and configures
    the physical interface type (e1, t1, datacom variants, etc.) independently
    of the global function mode.

TdmInterface values (from ATSL-TDM-PORT-MIB::TdmInterface):
    0  = none           — port disabled
    1  = g703e1         — E1 (2048 kb/s, ITU-T G.703)
    2  = clock          — clock I/O only
    3  = g703e0         — E0 variable-rate G.703
    4  = v11x21         — V.11 / X.21 datacom
    5  = v24v28         — V.24 / V.28 datacom
    6  = v35            — V.35 datacom
    7  = v36            — V.36 datacom
    8  = eia530         — EIA-530 datacom
    9  = eia530a        — EIA-530A datacom
    10 = ansit1         — T1 (1544 kb/s, ANSI T1.102)
    11 = c3794          — IEEE C37.94 optical

TestPattern values (from ATSL-MIB::TestPattern):
    0  = prbs9          — PRBS 2^9  - 1
    1  = prbs11         — PRBS 2^11 - 1
    2  = prbs15         — PRBS 2^15 - 1  (most common for E1 BER)
    3  = prbs20         — PRBS 2^20 - 1
    4  = prbs23         — PRBS 2^23 - 1  (ITU-T O.151)
    5  = prbs29         — PRBS 2^29 - 1
    6  = prbs31         — PRBS 2^31 - 1
    7  = allOnes        — all-ones (AIS)
    8  = allZeros       — all-zeros
    9  = user           — 32-bit user-defined (set tdmPortPatternTxFixed too)
    10 = qrss           — QRSS (Quasi-Random Signal Source)
    11 = alternating    — alternating 10101010…

Usage:
    python ex10_tdm_port_config.py <device_ip> [port_index]

Warning:
    This script modifies port mode and BER pattern — it changes test
    configuration on the device. Run only when no active test is in progress.
    Original values are saved and restored at the end.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_snmp_core import MultifunctionDevice, FunctionType, TRUTH_VALUE

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEVICE_IP  = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.100'
PORT_INDEX = int(sys.argv[2]) if len(sys.argv) > 2 else 1

# Target port mode configuration (tdmPortModeTable)
TARGET_MODE = {
    # TdmInterface: 1 = G.703 E1 (2048 kb/s)
    'tdmPortModeInterface': 1,
}

# Target BER pattern configuration (tdmPortPatternTable)
TARGET_PATTERN = {
    # TestPattern: 2 = PRBS-15 (ITU-T O.151, standard for E1 BER tests)
    'tdmPortPatternTx': 2,    # transmitted pattern
    'tdmPortPatternRx': 2,    # expected / analyzed pattern
    # tdmPortPatternTxFixed and tdmPortPatternRxFixed only matter when
    # pattern type is 'user' (9). Not written here.
}

TDM_PORT_MIB = 'ATSL-TDM-PORT-MIB'

# Human-readable labels for display
INTERFACE_NAMES = {
    0: 'none', 1: 'g703e1 (E1)', 2: 'clock', 3: 'g703e0',
    4: 'v11x21', 5: 'v24v28', 6: 'v35', 7: 'v36',
    8: 'eia530', 9: 'eia530a', 10: 'ansit1 (T1)', 11: 'c3794',
}
PATTERN_NAMES = {
    0: 'PRBS-9', 1: 'PRBS-11', 2: 'PRBS-15', 3: 'PRBS-20',
    4: 'PRBS-23', 5: 'PRBS-29', 6: 'PRBS-31', 7: 'allOnes',
    8: 'allZeros', 9: 'user', 10: 'QRSS', 11: 'alternating',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def write_and_verify(device: MultifunctionDevice, mib: str, oid: str,
                            value: int, index: int,
                            timeout: float = 5.0) -> bool:
    """Write a single integer OID and poll until the device confirms it."""
    ok = await device.set(mib, oid, value, index)
    if not ok:
        print(f"    ✗ SET rejected: {oid} = {value}")
        return False

    deadline = asyncio.get_event_loop().time() + timeout
    readback = None
    while asyncio.get_event_loop().time() < deadline:
        readback = await device.get(mib, oid, index)
        if readback is not None and int(readback) == value:
            return True
        await asyncio.sleep(0.2)

    print(f"    ✗ Verification timed out: {oid} — last read: {readback}")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():

    async with MultifunctionDevice(DEVICE_IP) as device:

        # ------------------------------------------------------------------
        # Step 1: Ensure TDM Endpoint mode is active on multifunction devices.
        # On dedicated E1 testers (non-multifunction) this step is skipped.
        # ------------------------------------------------------------------
        print("=== Step 1: Checking / switching function mode ===")
        if await device.is_multifunction():
            ok = await device.ensure_function(FunctionType.TDM_ENDPOINT)
            if not ok:
                print("  ERROR: Could not switch to TDM_ENDPOINT mode.")
                return
            active = await device.get_active_function()
            print(f"  Active function: {active.name if active else 'unknown'}")
        else:
            print("  Device is not multifunction — assuming TDM mode is active.")

        # ------------------------------------------------------------------
        # Step 2: Read and display the current port mode (tdmPortModeTable).
        # ------------------------------------------------------------------
        print(f"\n=== Step 2: Current port mode (port {PORT_INDEX}) ===")

        block_name = await device.get(TDM_PORT_MIB, 'tdmPortModeBlockName', PORT_INDEX)
        curr_iface  = await device.get(TDM_PORT_MIB, 'tdmPortModeInterface',  PORT_INDEX)
        curr_status = await device.get(TDM_PORT_MIB, 'tdmPortModeStatus',     PORT_INDEX)

        print(f"  tdmPortModeBlockName  = {block_name}")
        print(f"  tdmPortModeInterface  = {curr_iface} "
              f"({INTERFACE_NAMES.get(int(curr_iface) if curr_iface is not None else -1, '?')})")
        print(f"  tdmPortModeStatus     = {curr_status}  "
              f"(1=active, 2=notInService, 3=notReady, 5=createAndWait, 6=destroy)")

        # ------------------------------------------------------------------
        # Step 3: Read and display the current BER pattern (tdmPortPatternTable).
        # ------------------------------------------------------------------
        print(f"\n=== Step 3: Current BER pattern (port {PORT_INDEX}) ===")

        curr_tx  = await device.get(TDM_PORT_MIB, 'tdmPortPatternTx', PORT_INDEX)
        curr_rx  = await device.get(TDM_PORT_MIB, 'tdmPortPatternRx', PORT_INDEX)
        curr_txf = await device.get(TDM_PORT_MIB, 'tdmPortPatternTxFixed', PORT_INDEX)
        curr_rxf = await device.get(TDM_PORT_MIB, 'tdmPortPatternRxFixed', PORT_INDEX)

        print(f"  tdmPortPatternTx       = {curr_tx}  "
              f"({PATTERN_NAMES.get(int(curr_tx) if curr_tx is not None else -1, '?')})")
        print(f"  tdmPortPatternRx       = {curr_rx}  "
              f"({PATTERN_NAMES.get(int(curr_rx) if curr_rx is not None else -1, '?')})")
        print(f"  tdmPortPatternTxFixed  = {curr_txf}  (user pattern, hex)")
        print(f"  tdmPortPatternRxFixed  = {curr_rxf}  (user pattern, hex)")

        # ------------------------------------------------------------------
        # Step 4: Also read tdmPortEnable (scalar .0) to show test run state.
        # ------------------------------------------------------------------
        print(f"\n=== Step 4: TDM port enable state ===")
        tdm_enable = await device.get(TDM_PORT_MIB, 'tdmPortEnable', 0)
        print(f"  tdmPortEnable = {tdm_enable}  "
              f"({TRUTH_VALUE.get(int(tdm_enable) if tdm_enable is not None else -1, '?')})")

        # ------------------------------------------------------------------
        # Step 5: Apply the target port mode.
        # tdmPortModeInterface is read-write once the row is active.
        # No RowStatus manipulation is needed — the row exists by default.
        # ------------------------------------------------------------------
        print(f"\n=== Step 5: Applying port mode (port {PORT_INDEX}) ===")
        mode_ok = True
        for oid, value in TARGET_MODE.items():
            label = INTERFACE_NAMES.get(value, str(value))
            print(f"  Setting {oid} → {value} ({label})")
            result = await write_and_verify(device, TDM_PORT_MIB, oid, value, PORT_INDEX)
            if result:
                print(f"    ✓ confirmed")
            mode_ok = mode_ok and result

        print(f"\n  Port mode config: {'OK' if mode_ok else 'PARTIAL FAILURE'}")

        # ------------------------------------------------------------------
        # Step 6: Apply the target BER pattern.
        # Pattern writes take effect immediately; no generator restart needed.
        # ------------------------------------------------------------------
        print(f"\n=== Step 6: Applying BER pattern (port {PORT_INDEX}) ===")
        pat_ok = True
        for oid, value in TARGET_PATTERN.items():
            label = PATTERN_NAMES.get(value, str(value))
            print(f"  Setting {oid} → {value} ({label})")
            result = await write_and_verify(device, TDM_PORT_MIB, oid, value, PORT_INDEX)
            if result:
                print(f"    ✓ confirmed")
            pat_ok = pat_ok and result

        print(f"\n  BER pattern config: {'OK' if pat_ok else 'PARTIAL FAILURE'}")

        # ------------------------------------------------------------------
        # Step 7: Summary read-back — print the final state.
        # ------------------------------------------------------------------
        print(f"\n=== Step 7: Final state (port {PORT_INDEX}) ===")
        final_iface = await device.get(TDM_PORT_MIB, 'tdmPortModeInterface', PORT_INDEX)
        final_tx    = await device.get(TDM_PORT_MIB, 'tdmPortPatternTx',     PORT_INDEX)
        final_rx    = await device.get(TDM_PORT_MIB, 'tdmPortPatternRx',     PORT_INDEX)

        print(f"  Interface  : {final_iface} "
              f"({INTERFACE_NAMES.get(int(final_iface) if final_iface is not None else -1, '?')})")
        print(f"  TX pattern : {final_tx} "
              f"({PATTERN_NAMES.get(int(final_tx) if final_tx is not None else -1, '?')})")
        print(f"  RX pattern : {final_rx} "
              f"({PATTERN_NAMES.get(int(final_rx) if final_rx is not None else -1, '?')})")

        # ------------------------------------------------------------------
        # Step 8: Restore original values.
        # ------------------------------------------------------------------
        print(f"\n=== Step 8: Restoring original configuration ===")
        original_iface = curr_iface
        original_tx    = curr_tx
        original_rx    = curr_rx

        if original_iface is not None:
            await device.set(TDM_PORT_MIB, 'tdmPortModeInterface', int(original_iface), PORT_INDEX)
        if original_tx is not None:
            await device.set(TDM_PORT_MIB, 'tdmPortPatternTx', int(original_tx), PORT_INDEX)
        if original_rx is not None:
            await device.set(TDM_PORT_MIB, 'tdmPortPatternRx', int(original_rx), PORT_INDEX)

        print("  Restore complete.")


if __name__ == '__main__':
    asyncio.run(main())
