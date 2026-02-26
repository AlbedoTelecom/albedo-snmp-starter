# Copyright 2026 Albedo Telecom
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0
#!/usr/bin/env python3

"""
ALBEDO SNMP Core Utilities (Streamlined)

Core async SNMP operations for ALBEDO devices.
Based on PySNMP 7.1 async API.

Example:
    >>> import asyncio
    >>> from albedo_snmp_core import SNMPDevice
    >>> 
    >>> async def main():
    ...     device = SNMPDevice('192.168.1.100')
    ...     value = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 0)
    ...     print(value)
    >>> 
    >>> asyncio.run(main())
"""

import asyncio
import time
from pathlib import Path
from pysnmp.hlapi.v3arch.asyncio import *
from pysnmp.proto.rfc1902 import Integer, OctetString, Unsigned32
from enum import Enum

# Import albedo_mib_core from the same directory as THIS file.
# A plain 'from albedo_mib_core import ...' fails when src/ is not in sys.path,
# which silently sets _AlbedoMibManagerClass = None and causes all OID resolution
# to fall back to symbolic ObjectIdentity — which the SnmpEngine's own MibBuilder
# then fails to resolve.
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))

try:
    from albedo_mib_core import AlbedoMibManager as _AlbedoMibManager
    _AlbedoMibManagerClass = _AlbedoMibManager
except Exception as _e:
    import warnings
    warnings.warn(f"albedo_mib_core import failed: {_e}. SNMP operations will not resolve ALBEDO MIB names.")
    _AlbedoMibManagerClass = None

_mib_manager = None  # Created on first use via _get_mib_manager()


def _get_mib_manager():
    """Return the shared MIB manager, creating it on first call."""
    global _mib_manager
    if _mib_manager is None and _AlbedoMibManagerClass is not None:
        _mib_manager = _AlbedoMibManagerClass()
    return _mib_manager


class SNMPDevice:
    """
    Async SNMP client for ALBEDO devices.
    
    All methods are async and must be awaited.
    
    Example:
        >>> device = SNMPDevice('192.168.1.100')
        >>> value = await device.get('SNMPv2-MIB', 'sysDescr', 0)
        >>> await device.set('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 1, 0)
        >>> await device.cleanup()
    """
    
    def __init__(self, ip_address, read_community='public', write_community='private', port=161):
        """
        Initialize SNMP device connection.
        
        Args:
            ip_address (str): Device IP address
            read_community (str): SNMP read community
            write_community (str): SNMP write community
            port (int): SNMP port (default: 161)
        """
        self.ip_address = ip_address
        self.port = port
        self.read_community = read_community
        self.write_community = write_community
        
        # Create single engine (important for avoiding socket leaks!)
        self.engine = SnmpEngine()
        
        # Create auth objects
        self.read_auth = CommunityData(read_community, mpModel=1)  # SNMPv2c
        self.write_auth = CommunityData(write_community, mpModel=1)
        
        # Transport will be created async
        self.target = None
        self.context = ContextData()
        
    async def _ensure_target(self):
        """Create transport target if not already created."""
        if self.target is None:
            self.target = await UdpTransportTarget.create((self.ip_address, self.port))
        return self.target
    
    async def get(self, mib_name, oid_name, *indices):
        """
        Read a single OID value.
        
        Args:
            mib_name (str): MIB module name (e.g., 'ATSL-TDM-MONITOR-MIB')
            oid_name (str): OID name (e.g., 'tdmMonEnable')
            *indices: Variable number of index values for table entries
            
        Returns:
            Value from device, or None if error
            
        Example:
            >>> value = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 0)
        """
        await self._ensure_target()
        
        try:
            # Convert symbolic name to numeric OID using MibManager
            mgr = _get_mib_manager()
            if mgr:
                # Build symbolic OID string
                if indices:
                    symbolic_oid = f"{mib_name}::{oid_name}.{'.'.join(map(str, indices))}"
                else:
                    symbolic_oid = f"{mib_name}::{oid_name}"

                # Convert to numeric OID
                oid_to_use = mgr.name_to_oid(symbolic_oid)
            else:
                # Fallback: try symbolic name directly (will likely fail for ATSL MIBs)
                oid_to_use = ObjectIdentity(mib_name, oid_name, *indices)
            
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                self.engine,
                self.read_auth,
                self.target,
                self.context,
                ObjectType(ObjectIdentity(oid_to_use))
            )
            
            if errorIndication:
                print(f"Error: {errorIndication}")
                return None
            elif errorStatus:
                print(f"SNMP Error: {errorStatus.prettyPrint()}")
                return None
            else:
                return varBinds[0][1]
                
        except Exception as e:
            print(f"ERROR in get({mib_name}::{oid_name}): {e}")
            print("  Tip: run AlbedoMibManager().diagnose() to check MIB paths.")
            return None
    
    async def set(self, mib_name, oid_name, value, *indices):
        """
        Write a single OID value.
        
        Args:
            mib_name (str): MIB module name
            oid_name (str): OID name
            value: Value to write (int or str)
            *indices: Variable number of index values
            
        Returns:
            bool: True if successful, False otherwise
            
        Example:
            >>> success = await device.set('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 1, 0)
        """
        await self._ensure_target()
        
        try:
            # Auto-detect value type
            if isinstance(value, int):
                snmp_value = Integer(value)
            elif isinstance(value, str):
                snmp_value = OctetString(value)
            else:
                snmp_value = value  # Assume already correct type
            
            # Convert symbolic name to numeric OID using MibManager
            mgr = _get_mib_manager()
            if mgr:
                # Build symbolic OID string
                if indices:
                    symbolic_oid = f"{mib_name}::{oid_name}.{'.'.join(map(str, indices))}"
                else:
                    symbolic_oid = f"{mib_name}::{oid_name}"

                # Convert to numeric OID
                oid_to_use = mgr.name_to_oid(symbolic_oid)
            else:
                # Fallback: try symbolic name directly
                oid_to_use = ObjectIdentity(mib_name, oid_name, *indices)
            
            errorIndication, errorStatus, errorIndex, varBinds = await set_cmd(
                self.engine,
                self.write_auth,
                self.target,
                self.context,
                ObjectType(ObjectIdentity(oid_to_use), snmp_value)
            )
            
            if errorIndication:
                print(f"SET error: {errorIndication}")
                return False
            elif errorStatus:
                print(
                    f"SET SNMP error: {errorStatus.prettyPrint()} "
                    f"at {varBinds[int(errorIndex) - 1] if errorIndex else '?'}"
                )
                return False
            else:
                return True
                
        except Exception as e:
            print(f"ERROR in set({mib_name}::{oid_name}): {e}")
            print("  Tip: run AlbedoMibManager().diagnose() to check MIB paths.")
            return False
    
    async def walk(self, mib_name:str, table_name:str):
        """
        Walk through a table or subtree.
        
        Args:
            mib_name (str): MIB module name
            table_name (str): Table or subtree name
            
        Returns:
            list: List of (oid, value) tuples
            
        Example:
            >>> results = await device.walk('ATSL-TDM-MONITOR-MIB', 'tdmMonAnomaliesTable')
            >>> for oid, value in results:
            ...     print(f"{oid} = {value}")
        """
        await self._ensure_target()
        
        results = []
        
        # Convert symbolic name to numeric OID using MibManager
        mgr = _get_mib_manager()
        if mgr:
            symbolic_oid = f"{mib_name}::{table_name}"
            print(f"Walking {symbolic_oid} ...")
            current_oid = ObjectType(ObjectIdentity(mgr.name_to_oid(symbolic_oid)))
        else:
            current_oid = ObjectType(ObjectIdentity(mib_name, table_name))
        
        # Capture the starting numeric OID prefix before entering the loop.
        # Used to detect when the walk drifts outside the requested subtree —
        # lexicographicMode=False alone is not sufficient when current_oid is
        # updated from the raw returned OID object on each iteration.
        oid_prefix_str = mgr.name_to_oid(f"{mib_name}::{table_name}") if mgr else None

        try:
            while True:
                errorIndication, errorStatus, errorIndex, varBinds = await next_cmd(
                    self.engine,
                    self.read_auth,
                    self.target,
                    self.context,
                    current_oid,
                    lexicographicMode=False
                )
                
                if errorIndication:
                    print(f"Error: {errorIndication}")
                    break
                elif errorStatus:
                    print(f"SNMP Error: {errorStatus.prettyPrint()}")
                    break
                else:
                    if not varBinds:
                        break

                    for varBind in varBinds:
                        oid, value = varBind

                        # Stop at MIB boundary
                        if isinstance(value, (EndOfMibView, NoSuchObject, NoSuchInstance)):
                            return results

                        # Stop if returned OID has left the starting subtree
                        if oid_prefix_str and not str(oid).startswith(oid_prefix_str):
                            return results

                        results.append((str(oid), value))
                        current_oid = ObjectType(ObjectIdentity(oid))
                        
        except Exception as e:
            print(f"ERROR in walk({mib_name}::{table_name}): {e}")
            print("  Tip: run AlbedoMibManager().diagnose() to check MIB paths.")
        
        return results
    
    async def table_operation(self, mib_name:str, table_name:str, row_index:int, operations:dict):
        """
        Perform RowStatus-based table operation.
        
        Args:
            mib_name (str): MIB module name
            table_name (str): Table name (without 'Table' suffix)
            row_index (int): Row index to create/modify
            operations (dict): {column_name: value, ...}
                              Should include 'Status' with RowStatus values:
                              5 = createAndWait, 1 = active, 6 = destroy
            
        Returns:
            bool: True if successful
            
        Example:
            >>> ops = {
            ...     'Status': 5,  # createAndWait
            ...     'FileName': 'config.cfg',
            ...     'Action': 2,
            ... }
            >>> await device.table_operation('ATSL-CONFIG-FILES-MIB', 
            ...                              'configFilesOps', 1, ops)
        """
        try:
            for column, value in operations.items():
                full_column = f"{table_name}{column}"
                
                if not await self.set(mib_name, full_column, value, row_index):
                    print(f"Failed to set {full_column}")
                    return False
                
                # Small delay between operations
                await asyncio.sleep(0.1)
            
            return True
            
        except Exception as e:
            print(f"Exception in table_operation(): {e}")
            return False
    
    async def cleanup(self):
        """
        Clean up SNMP resources.
        
        IMPORTANT: Always call this when done to avoid socket leaks!
        
        Example:
            >>> device = SNMPDevice('192.168.1.100')
            >>> try:
            ...     value = await device.get(...)
            >>> finally:
            ...     await device.cleanup()
        """
        if self.engine:
            self.engine.close_dispatcher()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - auto cleanup."""
        await self.cleanup()
        return False


# Convenience functions for quick operations
async def quick_get(ip, mib_name, oid_name, *indices, community='public'):
    """
    Quick one-off read operation.
    
    Creates device, reads value, cleans up.
    
    Example:
        >>> value = await quick_get('192.168.1.100', 'SNMPv2-MIB', 'sysDescr', 0)
    """
    async with SNMPDevice(ip, read_community=community) as device:
        return await device.get(mib_name, oid_name, *indices)


async def quick_set(ip, mib_name, oid_name, value, *indices, community='private'):
    """
    Quick one-off write operation.
    
    Creates device, writes value, cleans up.
    
    Example:
        >>> success = await quick_set('192.168.1.100', 
        ...                           'ATSL-TDM-MONITOR-MIB', 
        ...                           'tdmMonEnable', 1, 0)
    """
    async with SNMPDevice(ip, write_community=community) as device:
        return await device.set(mib_name, oid_name, value, *indices)


# Multifunction device support
class FunctionType(Enum):
    """
    ALBEDO multifunction device modes.

    Each member encodes both the high-level function type (tdm/psn/clkmon)
    returned by mfActiveFunc and the specific operation mode returned by
    mfFuncMode in the matching mfFuncTable row.

    Mapping derived from:
      - ATSL-MULTIFUNCTION-MIB  MultiFunctionType  (mfActiveFunc)
      - ATSL-TDM-PORT-MIB       OperationMode      (mfFuncMode when tdm)
      - ATSL-PSN-GENERATOR-MIB  EndpointMode       (mfFuncMode when psn)
      - ATSL-MULTIFUNCTION-MIB  clkmon inline      (mfFuncMode when clkmon)
    """
    # TDM function (mfFuncType=1) — ATSL-TDM-PORT-MIB::OperationMode
    TDM_MONITOR      = (1, 0)
    TDM_ENDPOINT     = (1, 1)
    TDM_THROUGH      = (1, 2)
    E0_ENDPOINT      = (1, 3)
    DATA_ENDPOINT    = (1, 4)
    DATA_MONITOR     = (1, 5)
    C3794_ENDPOINT   = (1, 6)
    C3794_MONITOR    = (1, 7)
    TDM_EXTERNAL     = (1, 8)

    # PSN function (mfFuncType=2) — ATSL-PSN-GENERATOR-MIB::EndpointMode
    PSN_L1_ENDPOINT  = (2, 0)
    PSN_ETH_ENDPOINT = (2, 1)
    PSN_IP_ENDPOINT  = (2, 2)
    PSN_EXTERNAL     = (2, 3)

    # Clock monitor function (mfFuncType=3) — inline in ATSL-MULTIFUNCTION-MIB
    CLKMON_EXTERNAL  = (3, 0)
    CLKMON_ACTIVE    = (3, 1)


# Lookup table: (mfFuncType, mfFuncMode) → FunctionType
_FUNC_TYPE_MAP = {ft.value: ft for ft in FunctionType}

class MultifunctionDevice(SNMPDevice):
    """
    Extended SNMPDevice for multifunction ALBEDO testers.

    Handles detection and safe mode switching for devices like xGenius.
    Mode is identified by reading both mfActiveFunc (high-level function
    type) and mfFuncMode from the matching mfFuncTable row (specific mode
    within that function).

    Example:
        >>> async with MultifunctionDevice('192.168.1.100') as device:
        ...     await device.ensure_function(FunctionType.PSN_ETH_ENDPOINT)
        ...     await device.set('ATSL-PSN-MONITOR-MIB', 'psnMonEnable', 1, 0)
    """

    def __init__(self, ip_address, read_community='public', write_community='private'):
        """Initialize multifunction device."""
        super().__init__(ip_address, read_community, write_community)
        self._current_function = None
        self._is_multifunction = None

    async def is_multifunction(self):
        """
        Check if device supports multifunction operation.

        Uses mfActiveFunc.0 as the probe — a successful read means the
        ATSL-MULTIFUNCTION-MIB is present and the device is multifunction.
        """
        if self._is_multifunction is not None:
            return self._is_multifunction

        result = await self.get('ATSL-MULTIFUNCTION-MIB', 'mfActiveFunc', 0)
        self._is_multifunction = result is not None
        return self._is_multifunction

    async def get_active_function(self):
        """
        Get the currently active function mode.

        Performs a two-step lookup:
          1. Read mfActiveFunc to get the high-level function type
             (1=tdm, 2=psn, 3=clkmon).
          2. Walk mfFuncTable to find the row matching that function type,
             then read mfFuncMode to get the specific operation mode.
          3. Combine (func_type, mode) to return the correct FunctionType.

        Returns:
            FunctionType member, or None if device is not multifunction
            or the mode cannot be determined.
        """
        if not await self.is_multifunction():
            return None

        # Step 1: high-level function type from mfActiveFunc
        active_raw = await self.get('ATSL-MULTIFUNCTION-MIB', 'mfActiveFunc', 0)
        if active_raw is None:
            return None
        func_type = int(active_raw)  # 1=tdm, 2=psn, 3=clkmon

        # Step 2: walk mfFuncTable to find the row for this function type
        # Each row has mfFuncType and mfFuncMode columns.
        # mfFuncType is column 2, mfFuncMode is column 3 (per MIB ::= entries).
        func_mode = None
        table_rows = await self.walk('ATSL-MULTIFUNCTION-MIB', 'mfFuncTable')

        # Group by row index to pair mfFuncType with mfFuncMode
        # OID format: ...mfFuncTable.1.<column>.<row_index>
        row_data = {}  # {row_index: {column: value}}
        for oid_str, value in table_rows:
            parts = oid_str.split('.')
            # Last element is row index, second-to-last is column number
            try:
                col   = int(parts[-2])
                row   = int(parts[-1])
                row_data.setdefault(row, {})[col] = int(value)
            except (ValueError, IndexError):
                continue

        # Find the row where mfFuncType (col 2) matches func_type
        for row_index, cols in row_data.items():
            if cols.get(2) == func_type:         # col 2 = mfFuncType
                func_mode = cols.get(3)          # col 3 = mfFuncMode
                break

        if func_mode is None:
            return None

        # Step 3: map (func_type, func_mode) → FunctionType
        self._current_function = _FUNC_TYPE_MAP.get((func_type, func_mode))
        return self._current_function

    async def switch_function(self, target_function, wait_time=3):
        """
        Switch device to a different function mode.

        Writes mfFuncMode on the mfFuncTable row matching the target
        function type. This is the correct procedure per the MIB —
        writing mfFuncMode triggers an automatic function switch, and
        mfActiveFunc updates to reflect the new active function.

        IMPORTANT: This stops all current test activity.

        Args:
            target_function (FunctionType): Desired function mode.
            wait_time (int): Seconds to wait after switching.

        Returns:
            bool: True if the switch was verified successfully.
        """
        if not await self.is_multifunction():
            print("Device is not multifunction")
            return False

        current = await self.get_active_function()
        if current == target_function:
            print(f"Already in {target_function.name} mode")
            return True

        target_func_type, target_func_mode = target_function.value

        # Find the mfFuncTable row index for the target function type
        table_rows = await self.walk('ATSL-MULTIFUNCTION-MIB', 'mfFuncTable')
        target_row = None
        for oid_str, value in table_rows:
            parts = oid_str.split('.')
            try:
                col = int(parts[-2])
                row = int(parts[-1])
                if col == 2 and int(value) == target_func_type:  # mfFuncType column
                    target_row = row
                    break
            except (ValueError, IndexError):
                continue

        if target_row is None:
            print(f"Function type {target_func_type} not found in mfFuncTable")
            return False

        print(f"Switching from {current.name if current else 'unknown'} to {target_function.name}...")

        # Write mfFuncMode on the matching row — this triggers the switch
        success = await self.set(
            'ATSL-MULTIFUNCTION-MIB', 'mfFuncMode', target_func_mode, target_row
        )
        if not success:
            print("Failed to write mfFuncMode")
            return False

        print(f"Waiting {wait_time}s for mode switch...")
        await asyncio.sleep(wait_time)

        new_func = await self.get_active_function()
        if new_func == target_function:
            print(f"✓ Successfully switched to {target_function.name}")
            return True
        else:
            print(f"✗ Switch failed — active function is {new_func.name if new_func else 'unknown'}")
            return False

    async def ensure_function(self, required_function):
        """
        Ensure device is in the required function mode.

        If already in the correct mode this is a no-op. Otherwise calls
        switch_function() to perform the transition.

        Args:
            required_function (FunctionType): Required function mode.

        Returns:
            bool: True if device is in the required mode.
        """
        if not await self.is_multifunction():
            return True

        current = await self.get_active_function()
        if current == required_function:
            return True

        return await self.switch_function(required_function)


# Test pattern mapping
PATTERN_MAP = {
    'prbs6': 19, 'prbs6i': 20,
    'prbs7': 21, 'prbs7i': 22,
    'prbs9': 23, 'prbs9i': 24,
    'prbs11': 0, 'prbs11i': 1,
    'prbs15': 2, 'prbs15i': 3,
    'prbs20': 4, 'prbs20i': 5,
    'prbs23': 6, 'prbs23i': 7,
    'prbs31': 25, 'prbs31i': 26,
    'qrss': 27, 'qrssi': 28, 'qbf': 29,
    'rpat': 8, 'jpat': 9, 'spat': 10,
    'hfpat': 11, 'lfpat': 12, 'mfpat': 13,
    'lcrpat': 14, 'scrpat': 15,
    'all0': 16, 'all1': 17,
    'user': 18, 'matchrx': 30
}

# TruthValue encoding used by ALBEDO MIBs (from SNMPv2-TC)
TRUTH_VALUE = {1: 'true (enabled)', 2: 'false (disabled)'}

# Performance standard codes for tdmMonPerformanceStandard (from ATSL-TDM-MONITOR-MIB)
TDM_PERFORMANCE_STANDARDS = {
                          0: 'none',
                          1: 'g821',
                          2: 'g826',
                          3: 'm2100'
                      }

# Test script
if __name__ == "__main__":
    import sys
    
    async def test_connection(ip):
        """Test basic SNMP connectivity."""
        print(f"Testing connection to {ip}...")
        
        async with SNMPDevice(ip) as device:
            value = await device.get('SNMPv2-MIB', 'sysDescr', 0)
            if value:
                print(f"✓ Connected: {value}")
                return True
            else:
                print(f"✗ Connection failed")
                return False
    
    if len(sys.argv) < 2:
        print("Usage: python albedo_snmp_core.py <device_ip>")
        print("Example: python albedo_snmp_core.py 192.168.1.100")
        sys.exit(1)
    
    ip = sys.argv[1]
    success = asyncio.run(test_connection(ip))
    sys.exit(0 if success else 1)
