#!/usr/bin/env python3
"""
Example 07 — Table Operations (RowStatus)
==========================================
Demonstrates table_operation() for MIB tables that use the RowStatus
convention (RFC 2579) to create, modify and delete rows.

The RowStatus pattern is used by ALBEDO for:
  - ATSL-CONFIG-FILES-MIB  : file import / export / load / save
  - ATSL-LOG-FILES-MIB     : log file download
  - ATSL-REPORT-FILES-MIB  : report generation

ALBEDO RowStatus lifecycle for configFilesOpsTable:
  1. Set Status = createAndWait (5)  <- row created in notReady state
  2. Set FileName                    <- must match configFilesListTable
  3. Set Device                      <- required, typically 'internal'
  4. Set Action (e.g. save=33)       <- row transitions to notInService
  5. Set Status = active (1)         <- triggers the operation
  6. Poll Result until not inProgress (2)
  7. Set Status = destroy (6)        <- clean up the row

  Note: Device (col 3) is required. Without it the row stays notReady
  and the activation SET in step 5 returns inconsistentValue.

  Optional columns:
    configFilesOpsArgs  -- argument for rename/import/export (col 4)

Usage:
    python ex07_table_operation.py <device_ip>

Note:
    The actual execution block is commented out. Uncomment to run against
    a real device. The dry-run section prints the operation dict without
    touching the device.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_snmp_core import SNMPDevice
from albedo_mib_core import AlbedoMibManager


DEVICE_IP     = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.100'
ROW_INDEX     = 1       # Row index to use -- check configFilesOpsTable first to pick a free one
POLL_INTERVAL = 0.5     # seconds between result polls
POLL_TIMEOUT  = 30      # seconds before giving up


async def wait_for_completion(device: SNMPDevice, mib: str,
                               result_oid: str, index: int) -> str:
    """
    Poll a result OID until it leaves 'inProgress' (code 2).
    Returns the final result string.
    """
    result_codes = AlbedoMibManager().get_config_file_result_codes()

    deadline = asyncio.get_event_loop().time() + POLL_TIMEOUT
    while asyncio.get_event_loop().time() < deadline:
        raw = await device.get(mib, result_oid, index)
        if raw is None:
            break
        code = int(raw)
        status = result_codes.get(code, f"unknown({code})")
        print(f"  Result: {status} ({code})")
        if code != 2:  # not inProgress
            return status
        await asyncio.sleep(POLL_INTERVAL)

    return 'timeout'


async def main():

    async with SNMPDevice(DEVICE_IP) as device:

        manager      = AlbedoMibManager()
        action_codes = manager.get_config_file_action_codes()
        row_codes    = manager.get_row_status_codes()

        print("=== Config File Operations ===")
        print(f"Action codes : {action_codes}")
        print(f"RowStatus    : {row_codes}")
        print()

        # ------------------------------------------------------------------
        # Dry-run: show what a SAVE operation dict looks like.
        #
        # Columns written by table_operation() in order:
        #   configFilesOpsStatus    = createAndWait (5)  -- create row
        #   configFilesOpsFileName  = 'my_config.cfg'    -- target file
        #   configFilesOpsDevice    = 'internal'         -- required
        #   configFilesOpsAction    = save (33)          -- desired operation
        #
        # After table_operation() completes, a separate Status=active SET
        # triggers the operation. The two-step approach (createAndWait then
        # activate) is the correct sequence for this device -- the row must
        # be fully populated before activation or the agent returns
        # inconsistentValue.
        # ------------------------------------------------------------------
        save_operations = {
            'Status'  : row_codes['createAndWait'],   # 5 -- create row
            'FileName': 'my_config.cfg',              # must exist or will be created by save
            'Device'  : 'internal',                   # storage volume (required)
            'Action'  : action_codes['save'],         # 33
        }

        print("=== Operation dict for config SAVE (dry run) ===")
        for col, val in save_operations.items():
            full_col = f"configFilesOps{col}"
            print(f"  {full_col:<35s} = {val}")

        print()
        print("To execute, uncomment the block below and run against a real device.")
        print()

        # ------------------------------------------------------------------
        # Actual execution -- uncomment to run on a real device.
        #
        # Before running: walk configFilesListTable to confirm the device
        # name, and walk configFilesOpsTable to find a free row index.
        # ------------------------------------------------------------------
        # print("=== Executing config SAVE ===")
        #
        # # Steps 1-4: create row and populate columns
        # ok = await device.table_operation(
        #     'ATSL-CONFIG-FILES-MIB',
        #     'configFilesOps',
        #     ROW_INDEX,
        #     save_operations
        # )
        # if not ok:
        #     print("Failed to write operation parameters")
        #     return
        #
        # # Step 5: activate -- this triggers the operation
        # activated = await device.set(
        #     'ATSL-CONFIG-FILES-MIB', 'configFilesOpsStatus',
        #     row_codes['active'], ROW_INDEX
        # )
        # if not activated:
        #     print("Failed to activate row")
        #     return
        #
        # # Step 6: poll until done
        # print("Operation triggered -- waiting for completion...")
        # final_status = await wait_for_completion(
        #     device, 'ATSL-CONFIG-FILES-MIB', 'configFilesOpsResult', ROW_INDEX
        # )
        # print(f"Final result: {final_status}")
        #
        # # Step 7: destroy row -- client is responsible for cleanup
        # await device.set(
        #     'ATSL-CONFIG-FILES-MIB', 'configFilesOpsStatus',
        #     row_codes['destroy'], ROW_INDEX
        # )
        # print("Row destroyed")


if __name__ == '__main__':
    asyncio.run(main())