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
ALBEDO MIB Manager (Streamlined)

Handles MIB compilation and OID management for ALBEDO devices.

Example:
    >>> from albedo_mib_core import AlbedoMibManager
    >>> 
    >>> manager = AlbedoMibManager()
    >>> manager.compile_all_mibs()
    >>> oid = manager.name_to_oid('ATSL-TDM-MONITOR-MIB::tdmMonEnable')
"""

import os
import logging
from pathlib import Path
from pysnmp.smi import builder, view
# ObjectIdentity not needed: name_to_oid uses direct symbol lookup


class AlbedoMibManager:
    """
    Manager for ALBEDO MIB files.
    
    Handles MIB compilation from ASN.1 text to Python format,
    and provides OID name/number translation.
    """
    
    def __init__(self, mib_text_dir=None, mib_compiled_dir=None):
        """
        Initialize MIB manager.
        
        Args:
            mib_text_dir (str): Directory containing .txt MIB files
            mib_compiled_dir (str): Directory for compiled .py MIBs
        """
        # Default directories resolved relative to THIS FILE, not the CWD.
        # Using os.path.abspath('./...') would silently point to the wrong place
        # if the script is not launched from the project root.
        # Path(__file__).parent is the directory containing THIS file.
        # The mibs folder is a sibling of this file, not a child of 'src'.
        # e.g. if this file is at  project/src/albedo_mib_core.py
        #      mibs are at         project/src/mibs/text  and  project/src/mibs/compiled
        _here = Path(__file__).parent
        if mib_text_dir is None:
            mib_text_dir = _here / 'mibs' / 'text'
        if mib_compiled_dir is None:
            mib_compiled_dir = _here / 'mibs' / 'compiled' 
        
        self.mib_text_dir = Path(mib_text_dir)
        self.mib_compiled_dir = Path(mib_compiled_dir)
        
        # Create MIB builder
        self.mib_builder = builder.MibBuilder()

        # ALWAYS register the compiled MIB directory — even if it is empty or
        # does not exist yet. The production code does this unconditionally.
        # A conditional guard causes MibNotFoundError when compilation has not
        # been run yet, because the path is silently absent from the search path.
        self.mib_compiled_dir.mkdir(parents=True, exist_ok=True)
        self.mib_builder.add_mib_sources(
            builder.DirMibSource(str(self.mib_compiled_dir))
        )
        
        # Create MIB view controller for OID translation
        self.mib_view_controller = view.MibViewController(self.mib_builder)
        
        # Set up logging
        self.logger = logging.getLogger('AlbedoMibManager')
        self.logger.setLevel(logging.INFO)
        
        # Add console handler if none exists
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
            self.logger.addHandler(handler)
    
    def compile_mib(self, mib_name, force=False):
        """
        Compile a single MIB file from ASN.1 to Python.
        
        Args:
            mib_name (str): MIB name (without extension)
            force (bool): If True, recompile even if exists
            
        Returns:
            bool: True if successful
        """
        output_file = self.mib_compiled_dir / f"{mib_name}.py"
        
        # Skip if already compiled
        if output_file.exists() and not force:
            self.logger.info(f"✓ {mib_name} (already compiled)")
            return True
        
        try:
            # Try to import pysmi for compilation
            from pysmi.reader.localfile import FileReader
            from pysmi.searcher.pyfile import PyFileSearcher
            from pysmi.writer.pyfile import PyFileWriter
            from pysmi.parser.smi import parserFactory
            from pysmi.parser.dialect import smi_v1_relaxed
            from pysmi.codegen.pysnmp import PySnmpCodeGen
            from pysmi.compiler import MibCompiler
            
            # Ensure output directory exists
            self.mib_compiled_dir.mkdir(parents=True, exist_ok=True)
            
            # Create compiler
            mib_compiler = MibCompiler(
                parserFactory(**smi_v1_relaxed)(),
                PySnmpCodeGen(),
                PyFileWriter(str(self.mib_compiled_dir))
            )
            
            # Add source directories
            mib_compiler.add_sources(FileReader(str(self.mib_text_dir)))
            
            # Add common MIB locations
            for common_path in ['/usr/share/snmp/mibs', 
                               os.path.expanduser('~/.snmp/mibs')]:
                if os.path.exists(common_path):
                    mib_compiler.add_sources(FileReader(common_path))
            
            # Add searcher for dependencies
            mib_compiler.add_searchers(PyFileSearcher(str(self.mib_compiled_dir)))

            # Online MIB repository as fallback for standard dependencies
            try:
                from pysmi.reader.httpclient import HttpReader
                mib_compiler.add_sources(HttpReader('https://mibs.pysnmp.com/asn1/@mib@'))
            except Exception:
                pass  # Offline mode — local sources only

            # Compile
            results = mib_compiler.compile(mib_name, noDeps=False, rebuild=force)
            
            if results:
                success_states = {'compiled', 'untouched', 'borrowed'}

                # Log status for the MIB we were asked to compile, not the first
                # dependency entry returned by pysmi.
                target_result = results.get(mib_name)
                if target_result is None:
                    for module_name, result in results.items():
                        if module_name.lower() == mib_name.lower():
                            target_result = result
                            break

                if target_result is not None:
                    if str(target_result) in success_states:
                        self.logger.info(f"✓ {mib_name}")
                        return True
                    self.logger.error(f"✗ {mib_name}: {target_result}")
                    return False

                # Fallback: no direct entry for requested module in results.
                # Treat as success only if any module compiled successfully.
                if any(str(result) in success_states for result in results.values()):
                    self.logger.info(f"✓ {mib_name}")
                    return True

                first_module, first_result = next(iter(results.items()))
                self.logger.error(f"✗ {mib_name}: {first_module}: {first_result}")
                return False
            
            return False
            
        except ImportError as e:
            self.logger.error(f"pysmi library not available: {e}")
            self.logger.error("Install with: pip install pysmi")
            return False
        except Exception as e:
            self.logger.error(f"Error compiling {mib_name}: {e}")
            return False
    
    def compile_all_mibs(self, force=False):
        """
        Compile all MIB files in the text directory.
        
        Args:
            force (bool): If True, recompile all
            
        Returns:
            dict: {'success': [...], 'failed': [...]}
        """
        if not self.mib_text_dir.exists():
            self.logger.error(f"MIB text directory not found: {self.mib_text_dir}")
            return {'success': [], 'failed': []}
        
        # Find all MIB files
        mib_files = []
        for ext in ['*.txt', '*-MIB', '*.mib']:
            mib_files.extend(self.mib_text_dir.glob(ext))
        
        if not mib_files:
            self.logger.warning(f"No MIB files found in {self.mib_text_dir}")
            return {'success': [], 'failed': []}
        
        self.logger.info(f"Found {len(mib_files)} MIB file(s) to compile...")
        
        results = {'success': [], 'failed': []}
        
        for mib_file in mib_files:
            mib_name = mib_file.stem
            
            if self.compile_mib(mib_name, force=force):
                results['success'].append(mib_name)
            else:
                results['failed'].append(mib_name)
        
        self.logger.info(f"\nCompilation complete:")
        self.logger.info(f"  Success: {len(results['success'])}")
        self.logger.info(f"  Failed:  {len(results['failed'])}")
        
        return results
    
    def load_mib(self, mib_name):
        """
        Load a compiled MIB module.
        
        Args:
            mib_name (str): MIB name to load
            
        Returns:
            bool: True if successful
        """
        try:
            self.mib_builder.load_modules(mib_name)
            # Verify the module actually landed in mibSymbols
            if mib_name in self.mib_builder.mibSymbols:
                self.logger.info(f"Loaded MIB: {mib_name}")
                return True
            else:
                self.logger.error(
                    f"load_modules({mib_name!r}) ran without error but module is not "
                    f"in mibSymbols — the .py file may exist but failed to import. "
                    f"Compiled dir: {self.mib_compiled_dir}"
                )
                return False
        except Exception as e:
            self.logger.error(f"Error loading MIB {mib_name}: {e}")
            return False
    
    def name_to_oid(self, name:str):
        """
        Convert symbolic name to numeric OID.

        Reads the OID directly from the loaded MIB symbol object — no
        ObjectIdentity or resolveWithMib involved.  This avoids any
        dependency on the SnmpEngine's internal MibBuilder or PySNMP's
        auto-compilation path.

        Args:
            name (str): Symbolic name (e.g., 'ATSL-TDM-MONITOR-MIB::tdmMonEnable.0')

        Returns:
            str: Numeric OID (e.g., '1.3.6.1.4.1.39412.1.12.1.1.0')
        """
        try:
            if '::' not in name:
                # Already a numeric OID string - pass through unchanged
                return name

            module_name, object_parts = name.split('::', 1)
            parts = object_parts.split('.')
            object_name = parts[0]
            indices = parts[1:]  # may be empty

            # Load MIB if not already in mibSymbols
            if module_name not in self.mib_builder.mibSymbols:
                if not self.load_mib(module_name):
                    raise RuntimeError(
                        f"Could not load MIB module '{module_name}'. "
                        f"Compiled dir: {self.mib_compiled_dir} "
                        f"(exists={self.mib_compiled_dir.exists()}, "
                        f"py_files={len(list(self.mib_compiled_dir.glob('*.py')))})"
                    )

            # Read OID directly from the loaded symbol - no ObjectIdentity needed
            mib_symbols = self.mib_builder.mibSymbols.get(module_name, {})
            symbol_obj = mib_symbols.get(object_name)

            if symbol_obj is None:
                available = list(mib_symbols.keys())[1:10] # skip first entry which is the module itself
                raise RuntimeError(
                    f"Symbol '{object_name}' not found in MIB '{module_name}'. "
                    f"Available symbols (first 10): {available}"
                )

            if not hasattr(symbol_obj, 'getName'):
                raise RuntimeError(
                    f"Symbol '{object_name}' in '{module_name}' has no OID "
                    f"(type: {type(symbol_obj).__name__})"
                )

            oid_tuple = symbol_obj.getName()
            base_oid = '.'.join(map(str, oid_tuple))

            if indices:
                return base_oid + '.' + '.'.join(str(i) for i in indices)
            return base_oid

        except RuntimeError:
            raise  # don't double-wrap our own errors
        except Exception as e:
            raise RuntimeError(f"name_to_oid('{name}') failed: {e}") from e
    
    def oid_to_name(self, oid):
        """
        Convert numeric OID to symbolic name.
        
        Args:
            oid (str/tuple): Numeric OID
            
        Returns:
            str: Symbolic name
        """
        try:
            if isinstance(oid, str):
                oid = tuple(int(x) for x in oid.strip('.').split('.'))
            
            mib_name, symbol_name, suffix = self.mib_view_controller.getNodeLocation(oid)
            return f"{mib_name}::{symbol_name}.{'.'.join(map(str, suffix))}" if suffix else f"{mib_name}::{symbol_name}"
            
        except Exception as e:
            self.logger.debug(f"Could not resolve OID {oid}: {e}")
            return str(oid)
    
    # Helper methods for common OIDs and codes

    def diagnose(self):
        """
        Print diagnostic information about MIB paths and loaded modules.
        Call this when MIB resolution fails to identify the problem.

        Example:
            >>> manager = AlbedoMibManager()
            >>> manager.diagnose()
        """
        print("=" * 60)
        print("AlbedoMibManager Diagnostics")
        print("=" * 60)
        print(f"Text dir   : {self.mib_text_dir}")
        print(f"  exists   : {self.mib_text_dir.exists()}")
        print(f"Compiled dir: {self.mib_compiled_dir}")
        print(f"  exists   : {self.mib_compiled_dir.exists()}")
        if self.mib_compiled_dir.exists():
            py_files = list(self.mib_compiled_dir.glob('*.py'))
            print(f"  .py files: {len(py_files)}")
            for f in py_files[:10]:
                print(f"    {f.name}")
            if len(py_files) > 10:
                print(f"    ... and {len(py_files) - 10} more")
        print()
        print("MibBuilder search path:")
        for src in self.mib_builder.get_mib_sources():
            print(f"  {src}")
        print()
        print("Loaded MIB modules:")
        for name in sorted(self.mib_builder.mibSymbols.keys()):
            print(f"  {name}")
        print("=" * 60)

    def get_row_status_codes(self):
        """Get RFC 2579 RowStatus codes."""
        return {
            'active': 1,
            'notInService': 2,
            'notReady': 3,
            'createAndGo': 4,
            'createAndWait': 5,
            'destroy': 6
        }
    
    def get_config_file_action_codes(self):
        """Get ATSL-CONFIG-FILES-MIB action codes."""
        return {
            'idle': 0,
            'delete': 1,
            'rename': 2,
            'import': 3,
            'export': 4,
            'load': 32,
            'save': 33
        }
    
    def get_config_file_result_codes(self):
        """Get ATSL-CONFIG-FILES-MIB result codes."""
        return {
            0: "idle",
            1: "queued",
            2: "inProgress",
            3: "success",
            4: "fileNotFound",
            5: "deviceNotFound",
            6: "accessDenied",
            7: "readOnly",
            8: "notSupported",
            9: "internalError",
            10: "deviceFull",
            11: "entryExists",
            12: "dirNotEmpty",
            13: "mediaIO"
        }


def compile_all_mibs(mib_text_dir=None, mib_compiled_dir=None, force=False):
    """
    Convenience function to compile all MIBs.
    
    Args:
        mib_text_dir (str): Directory with .txt MIB files
        mib_compiled_dir (str): Output directory for .py files
        force (bool): Recompile even if exists
        
    Returns:
        dict: Compilation results
        
    Example:
        >>> from albedo_mib_core import compile_all_mibs
        >>> results = compile_all_mibs()
        >>> print(f"Compiled {len(results['success'])} MIBs")
    """
    manager = AlbedoMibManager(mib_text_dir, mib_compiled_dir)
    return manager.compile_all_mibs(force=force)


if __name__ == "__main__":
    """Run MIB compilation when executed directly."""
    import sys
    
    print("=" * 60)
    print("ALBEDO MIB Compiler")
    print("=" * 60)
    print()
    
    force = '--force' in sys.argv
    
    results = compile_all_mibs(force=force)
    
    if results['failed']:
        print("\nFailed MIBs:")
        for mib in results['failed']:
            print(f"  - {mib}")
        sys.exit(1)
    else:
        print("\n✓ All MIBs compiled successfully!")
        sys.exit(0)
