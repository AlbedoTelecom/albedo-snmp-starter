# ALBEDO SNMP Framework — Developer Reference

> **Scope:** Python developers automating ALBEDO xGenius or Net.Time devices via SNMP.
> Assumes familiarity with Python 3 and `async`/`await`; no prior PySNMP knowledge required.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Requirements & Installation](#2-requirements--installation)
3. [Quick Start](#3-quick-start)
4. [Module Reference: `albedo_mib_core`](#4-module-reference-albedo_mib_core)
5. [Module Reference: `albedo_snmp_core`](#5-module-reference-albedo_snmp_core)
6. [Common Patterns & Recipes](#6-common-patterns--recipes)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Overview

This framework provides a high-level Python API for automating ALBEDO Telecom test equipment
(xGenius, Net.Time) over SNMP. It abstracts PySNMP's low-level machinery into two focused
modules, letting you write automation scripts using human-readable MIB symbolic names
(`ATSL-TDM-MONITOR-MIB::tdmMonEnable`) rather than raw numeric OIDs.

The architecture is split into two layers. `albedo_mib_core` handles everything related to MIB
files: compiling ALBEDO's ASN.1 MIB definitions to Python, loading them into memory, and
translating symbolic names to numeric OIDs and back. `albedo_snmp_core` builds on top of it,
providing an async SNMP client (`SNMPDevice`) that uses `albedo_mib_core` for OID resolution and
exposes `get`, `set`, `walk`, and RowStatus table operations as simple awaitable methods.
`albedo_snmp_core` depends on `albedo_mib_core` and the two files must live in the same directory.

---

## 2. Requirements & Installation

### Python version

Python **3.8 or later** is required (async/await, `pathlib`, `importlib`).

### Required packages

```bash
# Core SNMP library (must be 7.1.x — the async API used here is not compatible with 6.x)
pip install pysnmp==7.1

# MIB compiler (required to compile ALBEDO .txt MIB files to Python)
pip install pysmi
```

> **Tip:** If you only need to run scripts against already-compiled MIBs (e.g. in a Docker image
> where compilation has already been done), `pysmi` is optional at runtime. It is only imported
> inside `compile_mib()` and its absence is reported as a clear `ImportError`.

### Required directory layout

Both modules resolve MIB paths **relative to their own location on disk** (see
[Design Notes](#design-notes) in section 4). The `mibs/` subtree must be a sibling of the two
`.py` files:

```
albedo-snmp-starter/
├── docs
│   ├── ALBEDO_MIB_Reference.md
│   └── REFERENCE.md
├── examples
│   ├── ex01_device_info.py
│   ├── ex02_read_albedo_mibs.py
│   ├── ex03_write_with_verify.py
│   ├── ex04_walk_table.py
│   ├── ex05_multifunction.py
│   ├── ex06_mib_manager.py
│   └── ex07_table_operation.py
├── README.md
├── requirements.txt
├── src
│   ├── albedo_mib_core.py
│   ├── albedo_snmp_core.py
│   └── mibs
│       ├── compiled
│       └── text


```

`mibs/compiled/` is created automatically by `AlbedoMibManager` if it does not exist — you do
not need to create it yourself.

### Co-location requirement

**Both `albedo_mib_core.py` and `albedo_snmp_core.py` must reside in the same directory.**
`albedo_snmp_core` imports its companion by prepending `Path(__file__).parent` to `sys.path` at
module load time. If the files are in different directories the import silently falls back to a
degraded mode where ALBEDO MIB names cannot be resolved (see
[Graceful Degradation](#design-notes-1) in section 5).

---

## 3. Quick Start

The following script is fully self-contained and runnable. It compiles any MIBs that have not
been compiled yet, connects to a device, reads and writes a value, then cleans up automatically
via the context manager.

```python
import asyncio
from albedo_mib_core import compile_all_mibs
from albedo_snmp_core import SNMPDevice

async def main():
    # Step 1 — compile MIBs (safe to call repeatedly; skips already-compiled files)
    results = compile_all_mibs()
    if results['failed']:
        print(f"Warning: {len(results['failed'])} MIB(s) failed to compile: {results['failed']}")

    # Step 2 — connect and operate; cleanup is automatic on context-manager exit
    async with SNMPDevice('192.168.1.100', read_community='public',
                          write_community='private') as device:

        # Read a scalar (instance .0)
        enabled = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 0)
        print(f"Monitor enabled: {enabled}")

        # Write a value (integer 1 = true/enabled in ALBEDO TruthValue encoding)
        success = await device.set('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 1, 0)
        print(f"Set result: {'OK' if success else 'FAILED'}")

        # Verify the write
        enabled = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 0)
        print(f"Monitor enabled after set: {enabled}")

    # cleanup() is called automatically on __aexit__; no manual call needed

asyncio.run(main())
```

---

## 4. Module Reference: `albedo_mib_core`

### `AlbedoMibManager`

Manager for ALBEDO MIB compilation and OID resolution. Wraps a PySNMP `MibBuilder` and
`MibViewController`, adding ALBEDO-specific path handling and convenience helpers.

#### `AlbedoMibManager.__init__`

```python
def __init__(
    self,
    mib_text_dir: str | Path | None = None,
    mib_compiled_dir: str | Path | None = None,
) -> None
```

Initialises the MIB builder, registers the compiled MIB directory in the search path, and
creates the compiled directory if it does not yet exist.

| Argument           | Type                  | Default                      | Description                                                         |
| ------------------ | --------------------- | ---------------------------- | ------------------------------------------------------------------- |
| `mib_text_dir`     | `str \| Path \| None` | `<module_dir>/mibs/text`     | Directory containing ASN.1 `.txt` / `*-MIB` source files.           |
| `mib_compiled_dir` | `str \| Path \| None` | `<module_dir>/mibs/compiled` | Directory where compiled `.py` MIB files are written and read from. |

**Returns:** `None`

---

#### `AlbedoMibManager.compile_mib`

```python
def compile_mib(self, mib_name: str, force: bool = False) -> bool
```

Compiles a single ASN.1 MIB file to Python using PySMI. Skips the file if the output `.py`
already exists, unless `force=True`.

| Argument   | Type   | Default | Description                                                      |
| ---------- | ------ | ------- | ---------------------------------------------------------------- |
| `mib_name` | `str`  | —       | Module name without extension, e.g. `'ATSL-TDM-MONITOR-MIB'`.    |
| `force`    | `bool` | `False` | When `True`, recompiles even if the output `.py` already exists. |

**Returns:** `bool` — `True` on success (including "already compiled" and "untouched" states from PySMI).

**Raises:** Does not raise; all errors are caught and logged, returning `False`.

```python
manager = AlbedoMibManager()
ok = manager.compile_mib('ATSL-TDM-MONITOR-MIB')
ok = manager.compile_mib('ATSL-TDM-MONITOR-MIB', force=True)  # force recompile
```

---

#### `AlbedoMibManager.compile_all_mibs`

```python
def compile_all_mibs(self, force: bool = False) -> dict[str, list[str]]
```

Discovers and compiles all MIB files in `mib_text_dir` (matching `*.txt`, `*-MIB`, `*.mib`).

| Argument | Type   | Default | Description                                  |
| -------- | ------ | ------- | -------------------------------------------- |
| `force`  | `bool` | `False` | Recompile all MIBs even if already compiled. |

**Returns:** `{'success': [list of compiled names], 'failed': [list of failed names]}`

```python
results = manager.compile_all_mibs()
print(f"Compiled: {len(results['success'])}, Failed: {len(results['failed'])}")
```

---

#### `AlbedoMibManager.load_mib`

```python
def load_mib(self, mib_name: str) -> bool
```

Loads a compiled MIB module into the `MibBuilder` so its symbols are available for OID
resolution. Called automatically by `name_to_oid()` on demand — you rarely need to call this
directly.

| Argument   | Type  | Default | Description                                 |
| ---------- | ----- | ------- | ------------------------------------------- |
| `mib_name` | `str` | —       | Module name, e.g. `'ATSL-TDM-MONITOR-MIB'`. |

**Returns:** `bool` — `True` if the module is now present in `mibSymbols`, `False` otherwise.

---

#### `AlbedoMibManager.name_to_oid`

```python
def name_to_oid(self, name: str) -> str
```

Converts a symbolic MIB name to its numeric dotted-decimal OID. Loads the relevant MIB module
on demand if it has not been loaded yet. If `name` contains no `::`, it is assumed to already be
a numeric OID and is returned unchanged.

> ⚠️ **Differs from standard PySNMP usage.** Standard PySNMP resolves OID names via
> `ObjectIdentity(...).resolveWithMib(mibViewController)`, which depends on the
> `SnmpEngine`'s internal `MibBuilder`. This method reads the OID tuple directly from
> `mibBuilder.mibSymbols` — bypassing `ObjectIdentity` entirely — so it is independent of
> any `SnmpEngine` instance.

| Argument | Type  | Default | Description                                                                                          |
| -------- | ----- | ------- | ---------------------------------------------------------------------------------------------------- |
| `name`   | `str` | —       | Symbolic name in `'MODULE::object'` or `'MODULE::object.index'` form, or a plain numeric OID string. |

**Returns:** `str` — numeric OID, e.g. `'1.3.6.1.4.1.39412.1.12.1.1.0'`.

**Raises:** `RuntimeError` if the MIB module cannot be loaded or the symbol is not found.

```python
manager = AlbedoMibManager()
oid = manager.name_to_oid('ATSL-TDM-MONITOR-MIB::tdmMonEnable.0')
# '1.3.6.1.4.1.39412.1.12.1.1.0'

oid = manager.name_to_oid('1.3.6.1.4.1.39412.1.12.1.1.0')  # passed through unchanged
```

---

#### `AlbedoMibManager.oid_to_name`

```python
def oid_to_name(self, oid: str | tuple) -> str
```

Converts a numeric OID to its symbolic `MODULE::object.suffix` representation using the
`MibViewController`. Falls back to returning the OID as a string if resolution fails.

| Argument | Type           | Default | Description                                      |
| -------- | -------------- | ------- | ------------------------------------------------ |
| `oid`    | `str \| tuple` | —       | Numeric OID as a dotted string or integer tuple. |

**Returns:** `str` — e.g. `'ATSL-TDM-MONITOR-MIB::tdmMonEnable'`, or the original OID string on failure.

---

#### `AlbedoMibManager.diagnose`

```python
def diagnose(self) -> None
```

Prints a human-readable diagnostic report: text/compiled directory paths, whether they exist,
the number of compiled `.py` files, the `MibBuilder` search path, and the list of currently
loaded MIB modules. Call this when MIB resolution is failing.

```python
manager = AlbedoMibManager()
manager.diagnose()
```

---

#### `AlbedoMibManager.get_row_status_codes`

```python
def get_row_status_codes(self) -> dict[str, int]
```

Returns the RFC 2579 `RowStatus` integer codes as a named dictionary.

**Returns:**

```python
{'active': 1, 'notInService': 2, 'notReady': 3,
 'createAndGo': 4, 'createAndWait': 5, 'destroy': 6}
```

---

#### `AlbedoMibManager.get_config_file_action_codes`

```python
def get_config_file_action_codes(self) -> dict[str, int]
```

Returns the `ATSL-CONFIG-FILES-MIB` action integer codes (idle, delete, rename, import, export,
load, save).

---

#### `AlbedoMibManager.get_config_file_result_codes`

```python
def get_config_file_result_codes(self) -> dict[int, str]
```

Returns the `ATSL-CONFIG-FILES-MIB` operation result codes (0 = idle … 13 = mediaIO) as an
integer-to-name mapping.

---

### Module-level convenience function

#### `compile_all_mibs`

```python
def compile_all_mibs(
    mib_text_dir: str | Path | None = None,
    mib_compiled_dir: str | Path | None = None,
    force: bool = False,
) -> dict[str, list[str]]
```

Thin wrapper that instantiates `AlbedoMibManager` and calls `compile_all_mibs()`. Convenient
for one-liners in setup scripts.

```python
from albedo_mib_core import compile_all_mibs
results = compile_all_mibs()
```

---

### Design Notes

**Why `Path(__file__).parent` instead of a relative path**

Using `os.path.abspath('./mibs/...')` or `Path('mibs/...')` resolves against the process's
*current working directory* at the time of import. If a script is launched from any directory
other than the project root — a common scenario in CI, cron jobs, or when called as a library —
the paths silently point nowhere, and MIB resolution fails with no obvious error message.
`Path(__file__).parent` always resolves relative to the file's own location on disk, making the
module location-independent.

**Why `add_mib_sources()` is called unconditionally, before any compilation**

PySNMP's `MibBuilder` only searches paths that have been explicitly registered. A conditional
guard such as `if mib_compiled_dir.exists()` would skip registration when the directory is
absent (i.e. before the first compile run), causing `name_to_oid()` to raise `MibNotFoundError`
even after successful compilation in the same process — because the newly-created directory was
never added to the search path. Registering the path unconditionally (while also creating the
directory with `mkdir(parents=True, exist_ok=True)`) ensures the path is always in the builder's
search list, regardless of timing.

---

## 5. Module Reference: `albedo_snmp_core`

### Module-level constants

| Name                        | Type             | Description                                                                         |
| --------------------------- | ---------------- | ----------------------------------------------------------------------------------- |
| `PATTERN_MAP`               | `dict[str, int]` | Maps BERT pattern names (`'prbs15'`, `'all0'`, …) to ALBEDO integer codes.          |
| `TRUTH_VALUE`               | `dict[int, str]` | Maps ALBEDO `TruthValue` integers (1/2) to `'true (enabled)'`/`'false (disabled)'`. |
| `TDM_PERFORMANCE_STANDARDS` | `dict[int, str]` | Maps `tdmMonPerformanceStandard` codes (0–3) to standard names (`'g826'`, …).       |

---

### `SNMPDevice`

Async SNMP client for a single ALBEDO device. Uses SNMPv2c. All operations are `async` and
must be `await`ed.

#### Constructor

```python
def __init__(
    self,
    ip_address: str,
    read_community: str = 'public',
    write_community: str = 'private',
    port: int = 161,
) -> None
```

| Argument          | Type  | Default     | Description                  |
| ----------------- | ----- | ----------- | ---------------------------- |
| `ip_address`      | `str` | —           | Device IP address.           |
| `read_community`  | `str` | `'public'`  | SNMP read community string.  |
| `write_community` | `str` | `'private'` | SNMP write community string. |
| `port`            | `int` | `161`       | UDP port.                    |

> ⚠️ **Differs from standard PySNMP usage.** A single `SnmpEngine` instance is created in
> `__init__` and reused for the entire lifetime of the device object. Standard PySNMP examples
> often create a new `SnmpEngine` per operation. See [Design Notes](#design-notes-1) below.

---

#### `SNMPDevice` — method summary

| Method                                                         | Async | Description                                                           |
| -------------------------------------------------------------- | ----- | --------------------------------------------------------------------- |
| `get(mib_name, oid_name, *indices)`                            | ✓     | Read a single OID value.                                              |
| `set(mib_name, oid_name, value, *indices)`                     | ✓     | Write a single OID value.                                             |
| `walk(mib_name, table_name)`                                   | ✓     | Walk a table or subtree; returns all `(oid, value)` pairs.            |
| `table_operation(mib_name, table_name, row_index, operations)` | ✓     | Execute a RowStatus-based multi-column table write.                   |
| `cleanup()`                                                    | ✓     | Release the `SnmpEngine` transport dispatcher. Always call when done. |

---

#### `SNMPDevice.get`

```python
async def get(self, mib_name: str, oid_name: str, *indices: int) -> Any | None
```

Reads a single OID. Returns the raw PySNMP value object (supports `int()`, `str()`, `bytes()`
coercion depending on type), or `None` on any error.

| Argument   | Type  | Description                                                   |
| ---------- | ----- | ------------------------------------------------------------- |
| `mib_name` | `str` | MIB module, e.g. `'ATSL-TDM-MONITOR-MIB'`.                    |
| `oid_name` | `str` | Object name, e.g. `'tdmMonEnable'`.                           |
| `*indices` | `int` | Index components. Use `0` for scalar instances (`.0` suffix). |

```python
# Scalar (instance .0)
value = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 0)

# Table cell: row index 1
delay = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonNetworkDelay', 1)
```

---

#### `SNMPDevice.set`

```python
async def set(self, mib_name: str, oid_name: str, value: int | str | Any, *indices: int) -> bool
```

Writes a single OID value. `int` is automatically wrapped as `Integer`, `str` as `OctetString`;
any other type is passed through as-is.

> ⚠️ **Differs from standard PySNMP usage.** Standard PySNMP `set_cmd` requires the caller to
> supply the correct SNMP type object (`Integer32`, `OctetString`, etc.). This method
> auto-detects `int` → `Integer` and `str` → `OctetString`. For other types (e.g. `Unsigned32`,
> `IpAddress`) you must pass an already-constructed PySNMP type object as `value`.

| Argument   | Type                | Description       |
| ---------- | ------------------- | ----------------- |
| `mib_name` | `str`               | MIB module.       |
| `oid_name` | `str`               | Object name.      |
| `value`    | `int \| str \| Any` | Value to write.   |
| `*indices` | `int`               | Index components. |

**Returns:** `bool` — `True` if the SET PDU was accepted without error.

---

#### `SNMPDevice.walk`

```python
async def walk(self, mib_name: str, table_name: str) -> list[tuple[str, Any]]
```

Walks a MIB subtree using repeated `GETNEXT` operations, stopping at the first OID that falls
outside the starting subtree. Returns a list of `(numeric_oid_string, value)` tuples.

> ⚠️ **Differs from standard PySNMP usage.** `lexicographicMode=False` alone is not sufficient
> to reliably stop at a subtree boundary when `current_oid` is updated from the raw returned OID
> object on each iteration. This implementation captures the starting OID prefix as a string and
> additionally checks `str(oid).startswith(oid_prefix_str)` on every returned varbind to enforce
> the boundary.

```python
rows = await device.walk('ATSL-TDM-MONITOR-MIB', 'tdmMonAnomaliesTable')
for oid_str, value in rows:
    print(f"{oid_str} = {value}")
```

---

#### `SNMPDevice.table_operation`

```python
async def table_operation(
    self,
    mib_name: str,
    table_name: str,
    row_index: int,
    operations: dict[str, int | str],
) -> bool
```

Executes a sequence of SET operations against columns of a RowStatus-managed table. Column
names are constructed as `table_name + column_suffix` (e.g. `'configFilesOps'` + `'Status'` →
`'configFilesOpsStatus'`). A 100 ms delay is inserted between each SET to respect ALBEDO agent
timing requirements.

| Argument     | Type   | Description                                                                |
| ------------ | ------ | -------------------------------------------------------------------------- |
| `mib_name`   | `str`  | MIB module.                                                                |
| `table_name` | `str`  | Base table name **without** the `'Table'` suffix, e.g. `'configFilesOps'`. |
| `row_index`  | `int`  | Row index to create/modify.                                                |
| `operations` | `dict` | `{column_suffix: value}` pairs, processed in insertion order.              |

**Returns:** `bool` — `True` if all SETs succeeded.

```python
ops = {
    'Status':   5,             # createAndWait
    'FileName': 'backup.cfg',
    'Action':   33,            # save
}
ok = await device.table_operation('ATSL-CONFIG-FILES-MIB', 'configFilesOps', 1, ops)
```

---

#### `SNMPDevice.cleanup`

```python
async def cleanup(self) -> None
```

Closes the `SnmpEngine` transport dispatcher, releasing all UDP sockets. **Always call this**
when the device object is no longer needed. The context manager (`async with`) calls it
automatically.

---

#### Context manager pattern

```python
async with SNMPDevice('192.168.1.100') as device:
    value = await device.get('SNMPv2-MIB', 'sysDescr', 0)
# cleanup() is called automatically here, even if an exception was raised
```

---

### `MultifunctionDevice`

Subclass of `SNMPDevice` with additional methods for devices that support multiple test
functions (e.g. xGenius). Adds function detection and safe mode switching.

```python
from albedo_snmp_core import MultifunctionDevice, FunctionType

async with MultifunctionDevice('192.168.1.100') as device:
    await device.ensure_function(FunctionType.PSN_ETH_ENDPOINT)
    ok = await device.set('ATSL-PSN-MONITOR-MIB', 'psnMonEnable', 1, 0)
```

#### `MultifunctionDevice.is_multifunction`

```python
async def is_multifunction(self) -> bool
```

Returns `True` if the device responds to `mfActiveFunc.0`. Result is cached after the first
call.

---

#### `MultifunctionDevice.get_active_function`

```python
async def get_active_function(self) -> FunctionType | None
```

Returns the current `FunctionType` by performing a two-step lookup: reading `mfActiveFunc` for
the high-level function type, then walking `mfFuncTable` to find the specific `mfFuncMode` on the
matching row. Returns `None` if the device is not multifunction or the mode cannot be
determined.

---

#### `MultifunctionDevice.switch_function`

```python
async def switch_function(
    self,
    target_function: FunctionType,
    wait_time: int = 3,
) -> bool
```

Switches the device to `target_function` by writing `mfFuncMode` on the correct `mfFuncTable`
row, then waiting `wait_time` seconds and verifying the switch via `get_active_function()`.

**Important:** This stops all current test activity on the device.

| Argument          | Type           | Default | Description                                     |
| ----------------- | -------------- | ------- | ----------------------------------------------- |
| `target_function` | `FunctionType` | —       | Desired mode.                                   |
| `wait_time`       | `int`          | `3`     | Seconds to wait after writing before verifying. |

**Returns:** `bool` — `True` if the device confirmed the new mode.

---

#### `MultifunctionDevice.ensure_function`

```python
async def ensure_function(self, required_function: FunctionType) -> bool
```

No-op if the device is already in `required_function`; otherwise calls `switch_function()`.
Use this as a safe guard at the top of any test that requires a specific function mode.

---

### `FunctionType`

`enum.Enum` whose members represent all combinable ALBEDO function modes. Each member's value
is a `(mfFuncType, mfFuncMode)` tuple.

| Member             | Value    | Description                       |
| ------------------ | -------- | --------------------------------- |
| `TDM_MONITOR`      | `(1, 0)` | TDM monitor / passive             |
| `TDM_ENDPOINT`     | `(1, 1)` | TDM endpoint / active             |
| `TDM_THROUGH`      | `(1, 2)` | TDM through mode                  |
| `E0_ENDPOINT`      | `(1, 3)` | E0 sub-channel endpoint           |
| `DATA_ENDPOINT`    | `(1, 4)` | Datacom endpoint                  |
| `DATA_MONITOR`     | `(1, 5)` | Datacom monitor                   |
| `C3794_ENDPOINT`   | `(1, 6)` | IEEE C37.94 endpoint              |
| `C3794_MONITOR`    | `(1, 7)` | IEEE C37.94 monitor               |
| `TDM_EXTERNAL`     | `(1, 8)` | TDM external clock source         |
| `PSN_L1_ENDPOINT`  | `(2, 0)` | Ethernet L1 endpoint              |
| `PSN_ETH_ENDPOINT` | `(2, 1)` | Ethernet endpoint                 |
| `PSN_IP_ENDPOINT`  | `(2, 2)` | IP endpoint                       |
| `PSN_EXTERNAL`     | `(2, 3)` | PSN external                      |
| `CLKMON_EXTERNAL`  | `(3, 0)` | Clock monitor, external reference |
| `CLKMON_ACTIVE`    | `(3, 1)` | Clock monitor, active measurement |

---

### Convenience functions

#### `quick_get`

```python
async def quick_get(
    ip: str,
    mib_name: str,
    oid_name: str,
    *indices: int,
    community: str = 'public',
) -> Any | None
```

Creates a temporary `SNMPDevice`, performs one GET, and cleans up. Suitable for ad-hoc checks
and simple scripts; not for tight loops (creates and destroys a transport on every call).

```python
value = await quick_get('192.168.1.100', 'SNMPv2-MIB', 'sysDescr', 0)
```

---

#### `quick_set`

```python
async def quick_set(
    ip: str,
    mib_name: str,
    oid_name: str,
    value: int | str,
    *indices: int,
    community: str = 'private',
) -> bool
```

Creates a temporary `SNMPDevice`, performs one SET, and cleans up.

```python
ok = await quick_set('192.168.1.100', 'ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 1, 0)
```

---

### Design Notes

**Why a single shared `SnmpEngine` is critical**

`SnmpEngine` allocates a UDP socket via its internal transport dispatcher. Creating a new
`SnmpEngine` for every `get`/`set` call — as many PySNMP examples do — creates one new socket
per operation and never closes the old ones. In a script that performs hundreds of operations
this grows to hundreds of open file descriptors, eventually causing `OSError: [Errno 24] Too
many open files`. The framework avoids this by creating `SnmpEngine` once in `SNMPDevice.__init__`
and reusing it for all operations on that device. `cleanup()` (or the context manager) closes it
with `engine.close_dispatcher()`.

**The lazy singleton MIB manager pattern**

A single module-level `AlbedoMibManager` instance is created on the first call to any
`SNMPDevice` method that needs OID resolution (via `_get_mib_manager()`). All `SNMPDevice`
instances in a process share the same manager. The practical consequence is that MIB modules are
loaded at most once per process — subsequent `get`/`set` calls for already-loaded MIBs pay no
extra cost. If you change compiled MIBs on disk and need them reloaded within the same process,
you must restart the interpreter (there is no public reload API).

**Graceful degradation when `albedo_mib_core` is unavailable**

At module import time, `albedo_snmp_core` attempts to import `AlbedoMibManager`. If the import
fails (e.g. `albedo_mib_core.py` is missing or has an error), a `warnings.warn()` is emitted
and the internal `_AlbedoMibManagerClass` is set to `None`. In this degraded mode, `get`, `set`,
and `walk` fall back to constructing a plain `ObjectIdentity(mib_name, oid_name)` and passing
it directly to PySNMP. This will succeed for standard IETF MIBs bundled with PySNMP
(`SNMPv2-MIB`, etc.) but will fail for ALBEDO-specific MIBs. The warning is emitted once at
import — if you see it, check that both files are in the same directory.

---

## 6. Common Patterns & Recipes

### Recipe 1 — Walking a results table

```python
import asyncio
from albedo_snmp_core import SNMPDevice

async def read_tdm_anomalies(ip: str) -> None:
    async with SNMPDevice(ip) as device:
        rows = await device.walk('ATSL-TDM-MONITOR-MIB', 'tdmMonAnomaliesTable')
        for oid_str, value in rows:
            # oid_str is a numeric dotted OID; value is a PySNMP type object
            print(f"  {oid_str} = {int(value)}")

asyncio.run(read_tdm_anomalies('192.168.1.100'))
```

---

### Recipe 2 — RFC 2579 RowStatus table operations (config file save)

ALBEDO file-operation tables follow the RFC 2579 RowStatus state machine.
The correct sequence is: **createAndWait (5) → set columns → activate (1) → poll result → destroy (6)**.

```python
import asyncio
from albedo_snmp_core import SNMPDevice
from albedo_mib_core import AlbedoMibManager

async def save_config(ip: str, filename: str) -> bool:
    mgr = AlbedoMibManager()
    actions = mgr.get_config_file_action_codes()
    results = mgr.get_config_file_result_codes()
    row_status = mgr.get_row_status_codes()
    ROW = 1  # arbitrary row index for this one-shot operation

    async with SNMPDevice(ip) as device:
        # Step 1 — create row in notReady/createAndWait state
        await device.set('ATSL-CONFIG-FILES-MIB', 'configFilesOpsStatus', row_status['createAndWait'], ROW)

        # Step 2 — populate columns
        await device.set('ATSL-CONFIG-FILES-MIB', 'configFilesOpsFileName', filename, ROW)
        await device.set('ATSL-CONFIG-FILES-MIB', 'configFilesOpsAction',   actions['save'],  ROW)

        # Step 3 — activate the row to trigger the operation
        await device.set('ATSL-CONFIG-FILES-MIB', 'configFilesOpsStatus', row_status['active'], ROW)

        # Step 4 — poll until result is no longer 'queued' or 'inProgress'
        for _ in range(30):
            await asyncio.sleep(1)
            raw = await device.get('ATSL-CONFIG-FILES-MIB', 'configFilesOpsResult', ROW)
            code = int(raw) if raw is not None else -1
            state = results.get(code, 'unknown')
            if state not in ('queued', 'inProgress'):
                # Step 5 — destroy the row regardless of outcome
                await device.set('ATSL-CONFIG-FILES-MIB', 'configFilesOpsStatus', row_status['destroy'], ROW)
                return state == 'success'

        # Timeout — clean up anyway
        await device.set('ATSL-CONFIG-FILES-MIB', 'configFilesOpsStatus', row_status['destroy'], ROW)
        return False

asyncio.run(save_config('192.168.1.100', 'baseline.cfg'))
```

---

### Recipe 3 — Switching function on a multifunction device

```python
import asyncio
from albedo_snmp_core import MultifunctionDevice, FunctionType

async def run_ethernet_test(ip: str) -> None:
    async with MultifunctionDevice(ip) as device:
        # ensure_function() is a no-op if already in the right mode
        if not await device.ensure_function(FunctionType.PSN_ETH_ENDPOINT):
            raise RuntimeError("Could not switch to Ethernet mode")

        await device.set('ATSL-PSN-MONITOR-MIB', 'psnMonEnable', 1, 0)
        print("Ethernet monitoring started")

asyncio.run(run_ethernet_test('192.168.1.100'))
```

---

### Recipe 4 — Error handling and cleanup in production scripts

```python
import asyncio
import logging
from albedo_snmp_core import SNMPDevice
from albedo_mib_core import compile_all_mibs

logging.basicConfig(level=logging.INFO)

async def production_test(ip: str) -> dict:
    # Compile once per deployment; safe to call every run (skips existing files)
    compile_results = compile_all_mibs()
    if compile_results['failed']:
        logging.warning("MIB compile failures: %s", compile_results['failed'])

    report = {}
    try:
        async with SNMPDevice(ip, read_community='public',
                              write_community='private') as device:
            # Each get() returns None on failure; check before use
            raw_delay = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonNetworkDelay', 0)
            if raw_delay is None:
                raise RuntimeError(f"Could not read delay from {ip}")
            report['delay_us'] = int(raw_delay)

            ok = await device.set('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 2, 0)  # disable
            if not ok:
                logging.error("Failed to disable monitor on %s", ip)
            # cleanup() is automatic on context-manager exit, even after exceptions

    except RuntimeError as exc:
        logging.error("Test failed: %s", exc)
        report['error'] = str(exc)

    return report

result = asyncio.run(production_test('192.168.1.100'))
print(result)
```

---

## 7. Troubleshooting

### `MibNotFoundError` or `RuntimeError: Could not load MIB module '…'`

**Cause:** `name_to_oid()` could not find the compiled `.py` file for a MIB module.

**Checklist:**

1. Run `compile_all_mibs()` (or `python albedo_mib_core.py`) before first use.
2. Check that `mibs/text/` contains the relevant `*-MIB.txt` source files.
3. Call `AlbedoMibManager().diagnose()` — it prints the exact paths being searched, whether
   the compiled directory exists, and how many `.py` files are in it.
4. Confirm that both `.py` framework files are in the same directory as the `mibs/` folder.
5. If `diagnose()` shows the path is correct but the module still fails to load, try
   `compile_mib('MODULE-NAME', force=True)` to force a clean recompile.

```python
from albedo_mib_core import AlbedoMibManager
AlbedoMibManager().diagnose()
```

---

### Socket exhaustion (`OSError: Too many open files`)

**Cause:** One or more code paths create a new `SNMPDevice` (and therefore a new `SnmpEngine`
and UDP socket) per operation inside a loop without calling `cleanup()`.

**Symptoms:** Script works for the first dozens of operations, then starts raising `OSError` or
timing out with no network-level explanation.

**Fix:** Always use `async with SNMPDevice(...) as device` or call `await device.cleanup()` in a
`finally` block. Never create `SNMPDevice` inside a tight loop; create it once outside the loop
and reuse it.

```python
# ✗ Wrong — creates a new socket on every iteration
for oid in oid_list:
    device = SNMPDevice(ip)
    await device.get(...)   # socket never closed

# ✓ Correct — one socket for the entire loop
async with SNMPDevice(ip) as device:
    for oid in oid_list:
        await device.get(...)
```

---

### OID resolution failure (`Symbol '…' not found in MIB '…'`)

**Cause:** The symbol name does not match what is defined in the compiled MIB, or the wrong MIB
module name was specified.

**Checklist:**

1. Verify the exact object name against the `OBJECT-TYPE` definition in the `.txt` source file
   (names are case-sensitive).
2. Verify the module name matches the `MODULE-IDENTITY` declaration, not just the filename.
3. The error message includes `Available symbols (first 10): [...]` — use this to discover the
   correct name.
4. For table scalars, remember that instances require an index suffix: pass `0` as `*indices`
   for `.0` scalars, or the row index for table entries.

```python
# ✗  Wrong index — missing the .0 instance suffix
value = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable')

# ✓  Correct
value = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 0)
```

---

### Multifunction device `inconsistentValue` on SET

**Cause:** An SNMP SET was attempted on a function-specific OID (e.g. a PSN monitor object)
while the device is currently in a different function mode (e.g. TDM). The ALBEDO agent rejects
writes to MIB objects that belong to an inactive function.

**Fix:** Always call `ensure_function()` before accessing function-specific OIDs.

```python
async with MultifunctionDevice(ip) as device:
    # Ensure PSN function is active BEFORE writing PSN OIDs
    await device.ensure_function(FunctionType.PSN_ETH_ENDPOINT)
    await device.set('ATSL-PSN-MONITOR-MIB', 'psnMonEnable', 1, 0)   # now safe
```

If you are seeing `inconsistentValue` errors on an apparently correct SET, add a call to
`get_active_function()` immediately before the failing SET to confirm which mode the device
actually reports — the function switch may have silently failed or timed out.
