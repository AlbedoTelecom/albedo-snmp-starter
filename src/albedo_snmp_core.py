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

def _find_mib_root_oid(mgr, mib_name: str) -> str | None:
    """
    Return the root OID for a MIB module — the symbol with the shortest OID tuple.

    Used by walk() when no table_name is given, so the walk covers the entire MIB.
    Loads the module first if it is not already in mibSymbols.
    """
    if mib_name not in mgr.mib_builder.mibSymbols:
        if not mgr.load_mib(mib_name):
            return None
    symbols = mgr.mib_builder.mibSymbols.get(mib_name, {})
    best_oid: str | None = None
    best_len = float('inf')
    for obj in symbols.values():
        if hasattr(obj, 'getName'):
            oid_tuple = obj.getName()
            if oid_tuple and len(oid_tuple) < best_len:
                best_len = len(oid_tuple)
                best_oid = '.'.join(map(str, oid_tuple))
    return best_oid

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
    
    async def walk(self, mib_name: str, table_name: str | None = None):
        """
        Walk through a MIB table, subtree, or the entire MIB module.

        Args:
            mib_name (str): MIB module name.
            table_name (str | None): Table or subtree name.
                If omitted (or None), the walk starts from the MIB's root
                object and covers all tables/scalars in that module.

        Returns:
            list: List of (oid, value) tuples.

        Examples:
            # Walk a specific table
            >>> results = await device.walk('ATSL-TDM-MONITOR-MIB', 'tdmMonAnomaliesTable')

            # Walk the entire MIB
            >>> results = await device.walk('ATSL-TDM-MONITOR-MIB')
        """
        await self._ensure_target()
        
        results = []

        # Convert symbolic name to numeric OID using MibManager
        mgr = _get_mib_manager()

        if table_name is None:
            # No specific table — resolve the MIB's root OID and walk the whole module.
            if mgr is None:
                print(f"ERROR in walk({mib_name}): MIB manager unavailable; "
                    f"cannot resolve MIB root OID without a table_name.")
                return results
            root_oid = _find_mib_root_oid(mgr, mib_name)
            if root_oid is None:
                print(f"ERROR in walk({mib_name}): could not resolve MIB root OID. "
                    f"Ensure MIBs are compiled and loaded.")
                return results
            print(f"Walking {mib_name} (root: {root_oid}) ...")
            current_oid = ObjectType(ObjectIdentity(root_oid))
            oid_prefix_str = root_oid
        elif mgr:
            symbolic_oid = f"{mib_name}::{table_name}"
            print(f"Walking {symbolic_oid} ...")
            current_oid = ObjectType(ObjectIdentity(mgr.name_to_oid(symbolic_oid)))
            oid_prefix_str = mgr.name_to_oid(symbolic_oid)
        else:
            current_oid = ObjectType(ObjectIdentity(mib_name, table_name))
            oid_prefix_str = None
        
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
            label = table_name or '<root>'
            print(f"ERROR in walk({mib_name}::{label}): {e}")
            print("  Tip: run AlbedoMibManager().diagnose() to check MIB paths.")
        
        return results
    
    async def walk_readable(self, mib_name: str, table_name: str | None = None,) -> list[tuple[str, str]]:
        """
        Walk a MIB subtree and return human-readable (symbolic_name, value) tuples.

        Calls walk() and translates each numeric OID to its symbolic name using
        oid_to_name().  Falls back to the raw numeric OID string if a symbol
        cannot be resolved (e.g. the MIB for that OID is not loaded).

        Args:
            mib_name (str): MIB module name.
            table_name (str | None): Table or subtree name; None walks the
                entire MIB module (same semantics as walk()).

        Returns:
            list[tuple[str, str]]: (symbolic_name, value_str) pairs, where
                value_str is produced by prettyPrint() when available, or str().

        Example:
            >>> rows = await device.walk_readable('ATSL-PSN-MONITOR-MIB', 'psnMonStatsTable')
            >>> for name, val in rows:
            ...     print(f"{name} = {val}")
            ATSL-PSN-MONITOR-MIB::psnMonStatsIndex.1 = 1
            ATSL-PSN-MONITOR-MIB::psnMonStatsFrames.1 = 232
        """
        raw = await self.walk(mib_name, table_name)
        mgr = _get_mib_manager()

        readable = []
        for oid_str, value in raw:
            symbolic = mgr.oid_to_name(oid_str) if mgr else oid_str
            value_str = value.prettyPrint() if hasattr(value, 'prettyPrint') else str(value)
            readable.append((symbolic, value_str))

        return readable
    
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
    ALBEDO xGenius function modes.

    Values are (mfFuncType, mfFuncMode) tuples confirmed by direct
    device observation.  They do NOT match the MIB textual-convention
    numeric definitions — the firmware uses a different mapping.

    Switching notes:
      - Use PSN_ETH_ENDPOINT as the safe PSN landing mode.
        Further PSN sub-mode selection (L1, IP endpoint, IP through)
        is done via the psnGenMode scalar after switching.
      - Use TDM_E1T1_ENDPOINT as the safe TDM landing mode.
        Further TDM interface selection is done via
        ATSL-TDM-PORT-MIB::tdmPortModeInterface after switching.
      - Index 1 (TDM row) values 1 and 6 activate PSN modes — firmware
        quirk.  Never write these values to the TDM row intentionally.
      - Index 3 (CLKMON row) does not work on tested firmware; all
        values produce TDM Datacom Monitor.  CLKMON omitted.
    """
    # TDM function (mfFuncType=1) — safe landing: TDM_E1T1_ENDPOINT
    TDM_E1T1_ENDPOINT = (1, 0)
    TDM_E1T1_MONITOR  = (1, 2)
    TDM_ANALOG        = (1, 4)
    TDM_DATACOM       = (1, 5)
    TDM_C3794         = (1, 7)

    # PSN function (mfFuncType=2) — safe landing: PSN_ETH_ENDPOINT
    PSN_CABLE_TEST    = (2, 0)
    PSN_ETH_ENDPOINT  = (2, 1)
    PSN_PRP_ENDPOINT  = (2, 2)
    PSN_EXTERNAL      = (2, 3)   # L1 / IP endpoint / IP through;
                                  # sub-mode selected via psnGenMode scalar


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

        # Phase 1: trigger the domain switch using mode 0 (safe for all domains:
        # tdmMonitor for TDM, l1Endpoint for PSN, external for clkmon).
        # The MIB requires landing in the target domain first; the specific
        # sub-mode is set in Phase 2 once the domain switch is confirmed.
        # Poll mfActiveFunc (a scalar GET) rather than walking mfFuncTable on
        # every iteration — much faster and avoids the 10-walk-per-second pattern.
        success = await self.set(
            'ATSL-MULTIFUNCTION-MIB', 'mfFuncMode', Unsigned32(target_func_mode), target_row
        )
        if not success:
            print(f"Failed to write mfFuncMode (target mode {target_func_mode})")
            return False

        print(f"Waiting up to {wait_time}s for domain switch "
            f"(target domain: {target_func_type})...")
        deadline = asyncio.get_event_loop().time() + wait_time
        while asyncio.get_event_loop().time() < deadline:
            active_raw = await self.get('ATSL-MULTIFUNCTION-MIB', 'mfActiveFunc', 0)
            if active_raw is not None and int(active_raw) == target_func_type:
                print(f"  Domain switch confirmed (mfActiveFunc = {target_func_type})")
                break
            await asyncio.sleep(0.5)
        else:
            active_raw = await self.get('ATSL-MULTIFUNCTION-MIB', 'mfActiveFunc', 0)
            print(f"✗ Domain switch timed out — mfActiveFunc = {active_raw}")
            return False

        # Verify final state
        new_func = await self.get_active_function()
        if new_func == target_function:
            print(f"✓ Successfully switched to {target_function.name}")
            return True
        else:
            print(f"✗ Mode verify failed — active function is "
                f"{new_func.name if new_func else 'unknown'}")
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


# Test pattern mapping: name → integer value (for SET operations).
# Source: ATSL-MIB::TestPattern TC (values 0-18) plus device-specific
# extensions observed on xGenius / Ether10.Genius hardware (values 19-30).
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

# Reverse of PATTERN_MAP: integer value → pattern name (for display).
# All values in PATTERN_MAP are unique so the inversion is unambiguous.
# Values not present here are device-specific extensions not yet catalogued;
# use a fallback like f'device-specific({n})' for unknown values.
PATTERN_NAMES = {v: k for k, v in PATTERN_MAP.items()}

# TdmInterface TC: integer value → interface name (for display).
# Source: ATSL-TDM-PORT-MIB::TdmInterface SYNTAX INTEGER block.
TDM_INTERFACE_NAMES = {
    0:  'disabled',
    1:  'g703e1 (E1, 2048 kb/s)',
    2:  'clock',
    3:  'g703e0',
    4:  'datacom',
    5:  'v11 (X.21/V.11)',
    6:  'v24 (V.24/V.28)',
    7:  'v35',
    8:  'v36 (RS-449)',
    9:  'eia530',
    10: 'eia530a',
    11: 'c3794 (IEEE C37.94)',
    12: 'ansit1 (T1, 1544 kb/s)',
}

# Delay test modes from ATSL-TDM-MONITOR-MIB, tdmMonDelayMode
DELAY_MODES = {
'twoway': 0,
'oneway': 1
}

# Additional useful mappings from ATSL-DATACOM-PORT-MIB
EMULATION_MODES = {
    'dte': 0,
    'dce': 1
}

OPERATION_MODES_DATACOM = {
    'synchronous': 0,
    'asynchronous': 1
}

TD_CLOCK_CIRCUITS = {
    'ttc': 0,
    'tc': 1
}

TX_CLOCK_SOURCES = {
    'synthesized': 0,
    'recovered': 1
}

LINE_RATES = {
    'kbpsnx64': 0,
    'kbpsnx56': 1,
    'user': 2,
    'bps1200': 3,
    'bps2400': 4,
    'bps4800': 5,
    'bps8000': 7,
    'bps9600': 8,
    'bps16000': 9,
    'bps19200': 10,
    'kbps32': 11,
    'kbps48': 12,
    'kbps72': 13,
    'kbps128': 14
}

# TruthValue encoding used by ALBEDO MIBs (from SNMPv2-TC)
TRUTH_VALUE = {1: 'true (enabled)', 2: 'false (disabled)'}

# LinkStatus display map — ATSL-PSN-PORT-MIB::psnPortLinkStatus
LINK_STATUS = {0: '10 Mbps', 1: '100 Mbps', 2: '1000 Mbps', 3: '10 Gbps', 4: 'No link'}

# Performance standard codes for tdmMonPerformanceStandard (from ATSL-TDM-MONITOR-MIB)
TDM_PERFORMANCE_STANDARDS = {
    0: 'none',
    1: 'g821',
    2: 'g826',
    3: 'm2100'
}

def print_walk_readable(
    results: list[tuple[str, str]],
    max_rows: int = 20,
) -> None:
    """
    Print walk_readable() results to stdout.

    Args:
        results: Output of walk_readable() — (symbolic_name, value_str) pairs.
        max_rows: Truncate output after this many rows (default 20).
    """
    if not results:
        print("  (empty)")
        return
    for name, val in results[:max_rows]:
        print(f"  {name} = {val}")
    if len(results) > max_rows:
        print(f"  ... and {len(results) - max_rows} more entries")

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