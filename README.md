# albedo-snmp-starter

A Python starter kit for automating ALBEDO Telecom test equipment via SNMP.

**Supported devices:** xGenius, Zeus, AT.2048, AT.One, Ether.Genius, Net.Storm, Net.Hunter, Net.Time

---

## Quick Start

**1. Clone the repository**

```bash
git clone https://github.com/yourusername/albedo-snmp-starter.git
cd albedo-snmp-starter
```

**2. Create and activate a virtual environment**

```bash
# Linux / macOS
python3 -m venv snmpy_venv
source snmpy_venv/bin/activate

# Windows
python -m venv snmpy_venv
snmpy_venv\Scripts\activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

This installs the two key dependencies: **PySNMP 7.1** (async SNMP client) and **PySMI** (MIB compiler).

**4. Compile the ALBEDO MIBs** *(one-time, required before first use)*

```bash
python src/albedo_mib_core.py
```

This converts the ALBEDO ASN.1 MIB definitions in `src/mibs/text/` to Python modules that PySNMP can load at runtime. The compiled files are written to `src/mibs/compiled/` and only need to be regenerated if the MIB source files change.

**5. Run the first example**

Open `examples/ex01_device_info.py`, set `DEVICE_IP` to your device's address, then:

```bash
python examples/ex01_device_info.py <device_ip>
```

---

## Project Structure

```
albedo-snmp-starter/
├── docs/
│   ├── ALBEDO_MIB_Reference.md          # OID catalogue for all ALBEDO MIB modules
│   └── ALBEDO_CORE-FILES_REFERENCE.md   # Full API reference for the two core modules
├── examples/
│   ├── ex01_device_info.py              # Read basic device identity over SNMP
│   ├── ex02_read_albedo_mibs.py         # Resolve and read ALBEDO-specific OIDs
│   ├── ex03_write_with_verify.py        # Write a value and confirm the change
│   ├── ex04_walk_table.py               # Walk a MIB table and iterate its rows
│   ├── ex05_multifunction.py            # Detect and switch function modes (xGenius)
│   ├── ex06_mib_manager.py              # Use AlbedoMibManager directly for OID work
│   ├── ex07_table_operation.py          # RowStatus table create/activate/destroy
│   ├── ex08_psn_full_workflow.py          # End-to-end Ethernet/PSN measurement workflow
│   └── ex09_tdm_ber_workflow.py         # End-to-end E1 BER measurement workflow
├── requirements.txt                     # PySNMP 7.1 + PySMI + other dependencies
├── src/
│   ├── albedo_mib_core.py               # MIB compilation, OID resolution, MIB constants
│   ├── albedo_snmp_core.py              # Async SNMP client (SNMPDevice, MultifunctionDevice)
│   └── mibs/
│       ├── compiled/                    # Auto-generated at runtime — do not edit manually
│       └── text/                        # Place ALBEDO .txt MIB source files here
```

---

## Examples

The examples form a progressive learning path. Each one introduces a new concept that later
examples build on.

| File                        | What it demonstrates                                                    | Key concept introduced                                            |
| --------------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `ex01_device_info.py`       | Read sysDescr, sysName, and firmware version from a live device         | Connecting with `SNMPDevice` and the `async with` context manager |
| `ex02_read_albedo_mibs.py`  | Read values from ALBEDO-specific MIBs by symbolic name                  | Using `MODULE::object` OID notation; automatic MIB loading        |
| `ex03_write_with_verify.py` | Write a configuration value and read it back to confirm                 | `device.set()` return value; write/verify pattern                 |
| `ex04_walk_table.py`        | Walk a results table and process every row                              | `device.walk()` and iterating `(oid, value)` pairs                |
| `ex05_multifunction.py`     | Detect the active function mode and switch to a different one           | `MultifunctionDevice`, `FunctionType`, `ensure_function()`        |
| `ex06_mib_manager.py`       | Resolve OIDs symbolically, reverse-lookup names, inspect loaded modules | `AlbedoMibManager` as a standalone tool; `diagnose()`             |
| `ex07_table_operation.py`   | Create a RowStatus row, configure it, activate it, then destroy it      | RFC 2579 RowStatus state machine; `device.table_operation()`      |
| `ex08_psn_full_workflow.py`   | Configure an Ethernet generator, run a measurement, collect SLA results | Full workflow combining multiple concepts from earlier examples    |
| `ex09_tdm_ber_workflow.py`  | Switch to E1 Endpoint, set BER test pattern, run a measurement, collect anomaly and line results | E1 BER workflow; `e1MonEnable` / `e1MonAnomaliesTable`; firmware conditional-access behaviour |

---

## Documentation

- [`docs/ALBEDO_MIB_Reference.md`](docs/ALBEDO_MIB_Reference.md) — OID catalogue covering all 34 ALBEDO MIB modules: purpose, key tables, dependencies, and automation use cases.
- [`docs/ALBEDO_CORE-FILES_REFERENCE.md`](docs/ALBEDO_CORE-FILES_REFERENCE.md) — Complete API reference for `albedo_mib_core` and `albedo_snmp_core`, including method signatures, args tables, design notes, and troubleshooting.
- [ALBEDO Telecom SNMP documentation](https://www.albedotelecom.com) — Official vendor SNMP documentation for xGenius, Zeus and Net.Time devices.

---

## Key Concepts

### Async API

All SNMP operations are `async` and must be awaited. Use `SNMPDevice` as an async context
manager to ensure the underlying transport is always cleaned up, even if an exception is raised.

```python
import asyncio
from src.albedo_snmp_core import SNMPDevice

async def main():
    async with SNMPDevice('192.168.1.100') as device:
        value = await device.get('ATSL-TDM-MONITOR-MIB', 'tdmMonEnable', 0)
        print(value)

asyncio.run(main())
```

### MIB Compilation

ALBEDO ships MIB definitions as ASN.1 text files. PySNMP requires compiled Python versions of
these files before it can resolve symbolic OID names. Compile once (or after any MIB update):

```python
from src.albedo_mib_core import AlbedoMibManager

manager = AlbedoMibManager()
results = manager.compile_all_mibs()
print(f"Compiled: {len(results['success'])}, Failed: {len(results['failed'])}")
```

### Conditional-Access OIDs

Some ALBEDO OIDs are writable only when the device is in a specific hardware or software
state, even if the MIB marks them as `read-write`. Attempting to write them outside that
state returns `noAccess`. The three patterns to be aware of:

| OID group | Writable only when |
|---|---|
| `psnPortCfgPhyLaserOn` | Connector = SFP |
| `psnPortCfgPhyForcedBitRate` | Autonegotiation = OFF |
| `psnGenModeCvidLocal` / CPCP | Encapsulation ≠ untagged |
| `psnGenModeDhcpEnabled` / IP fields | `psnGenMode` = `ipEndpoint` |
| `tdmPortModeInterface` | Interface licensed on the device |

`ex08_psn_full_workflow.py` demonstrates this pattern for PSN OIDs. The E1 BER workflow
(`ex09_tdm_ber_workflow.py`) documents the analogous TDM conditional-access rules discovered
empirically on xGenius hardware.

### InetAddressIPv4 Encoding

IPv4 addresses in ALBEDO PSN MIBs (`psnGenModeIpv4AddressStatic` and friends) use the
`InetAddressIPv4` type from `INET-ADDRESS-MIB`, which is `OCTET STRING (SIZE 4)` — four raw
bytes in network byte order. Passing a dotted-decimal Python string to `device.set()` sends
12 ASCII bytes and silently corrupts the value. Always encode with `socket.inet_aton()`:

```python
import socket
from pysnmp.proto.rfc1902 import OctetString

await device.set('ATSL-PSN-GENERATOR-MIB',
                 'psnGenModeIpv4AddressStatic',
                 OctetString(socket.inet_aton('192.168.10.1')),
                 port_index)
```

### Multifunction Device Mode Switching

xGenius and similar multifunction devices require a two-phase approach when switching
between function domains (e.g. PSN → TDM):

1. **Domain switch** — write `mfFuncMode` on the target function's row in `mfFuncTable`.
   Use the safe landing values confirmed empirically on xGenius hardware:
   - TDM: `mfFuncMode = 0` → E1/T1 Endpoint (active TX). Note: the `OperationMode` TC
     labels this `tdmMonitor(0)`, but the firmware activates Endpoint behaviour. Values 1
     and 6 on the TDM row cross into PSN — never write them to the TDM row.
   - PSN: `mfFuncMode = 1` → Ethernet Endpoint.
   Confirm completion by polling `mfActiveFunc` directly rather than walking the full table.

2. **Sub-mode configuration** — once in the target domain, configure the specific interface
   or mode using function-specific MIBs (`tdmPortModeTable`, `psnGenModeTable`, etc.).

Never write function-specific OIDs (TDM MIBs, PSN MIBs) while a different function domain
is active — the agent returns `inconsistentValue` or silently discards the write.

### RowStatus Table Operations

Many ALBEDO configuration tables follow the RFC 2579 RowStatus pattern: they act as job
queues where you create a row, populate it, then activate it to trigger the operation.
`table_operation()` handles the column writes in the correct order:

```python
async with SNMPDevice('192.168.1.100') as device:
    await device.table_operation(
        'ATSL-CONFIG-FILES-MIB',
        'configFilesOps',        # base table name (without 'Table' suffix)
        row_index=1,
        operations={
            'Status':   5,             # createAndWait — allocate the row
            'FileName': 'backup.cfg',  # configure parameters
            'Action':   33,            # save action code
            'Status':   1,             # active — trigger the operation
        }
    )
```

---

## Requirements

- Python ≥ 3.10
- PySNMP 7.1
- PySMI (required for MIB compilation)
- ALBEDO device with the SNMP option enabled and reachable over IP

---

## License

This project is licensed under the **[Apache License 2.0](LICENSE)**.

### Why Apache 2.0?

* **Commercial-friendly.** You may use, modify, and distribute this code in commercial products. The only obligations are to preserve existing copyright notices and provide attribution; you are not required to publish or share your modifications.

* **Explicit patent grant.** Apache 2.0 includes a patent licence from each contributor to all users, covering the contributor's own patents that are necessarily infringed by their contribution. This protects users against patent claims brought by the project's own contributors, but does not address claims by unrelated third parties.

* **As-is warranty disclaimer.** The software is provided without warranty of any kind. Users assume all responsibility for determining its fitness for their purposes.

* **Attribution-only.** Downstream users must retain copyright notices but are not required to open-source their own modifications — making this licence well-suited to proprietary test-automation pipelines built on top of this starter kit.