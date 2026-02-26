# Contributing to albedo-snmp-starter

Thank you for taking the time to contribute. This document covers the project architecture,
development setup, and the specific rules for each type of contribution.

---

## Project Architecture

The framework is split into two modules that must always reside in the same directory
(`src/`). `albedo_mib_core.py` handles everything MIB-related: compiling ALBEDO ASN.1
definitions to Python with PySMI, loading compiled modules into a shared `MibBuilder`,
translating symbolic names (`ATSL-TDM-MONITOR-MIB::tdmMonEnable`) to numeric OIDs and
back, and exposing MIB-specific constants such as RowStatus codes and file action codes.

`albedo_snmp_core.py` provides the async SNMP client layer — `SNMPDevice`,
`MultifunctionDevice`, `FunctionType`, and the `quick_get`/`quick_set` helpers. It depends
on `albedo_mib_core` via a path-safe import: at module load time it prepends
`Path(__file__).parent` to `sys.path`, then imports `AlbedoMibManager`. This means the two
files must stay in the same directory; moving either one without the other will break the
import and silently degrade OID resolution to a fallback mode that cannot resolve ALBEDO MIB
names.

---

## Development Setup

**1. Create and activate a virtual environment**

```bash
# Linux / macOS
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Verify MIB compilation**

After any change to the MIB source files or to `albedo_mib_core.py`, re-run the compiler
and check that all MIBs succeed:

```bash
python src/albedo_mib_core.py
```

A clean run should print `✓ All MIBs compiled successfully!`. If any MIB fails, call
`AlbedoMibManager().diagnose()` from a Python shell to inspect the search paths and loaded
modules.

**4. Run the examples against a real device**

There is no offline test suite for SNMP operations. Verify your changes by running the
relevant examples against a live xGenius or Net.Time device. At minimum, run
`ex01_device_info.py` to confirm basic connectivity and `ex06_mib_manager.py` to confirm
OID resolution is intact.

---

## Contribution Guidelines

### New examples

- **Naming:** `exNN_descriptive_name.py` where `NN` is the next available two-digit number.
- **Self-contained:** Each example must run as a standalone script with no dependencies
  outside `src/` and the standard library. Any required imports must work after the normal
  `pip install -r requirements.txt` step.
- **Module docstring:** Every example file must open with a docstring that states (a) what
  the script demonstrates, (b) which ALBEDO equipment it targets, and (c) which MIB(s) or
  API methods it exercises.
- **Build on prior examples:** A new example should assume the reader has already worked
  through all lower-numbered ones. Do not re-explain concepts that are covered earlier in the
  series; add a reference instead (`# See ex04_walk_table.py for walk() basics`).

### Changes to `albedo_snmp_core.py`

**The shared `SnmpEngine` pattern must not be broken.**
`SNMPDevice.__init__` creates exactly one `SnmpEngine` instance and reuses it for every
`get`, `set`, and `walk` call on that device. This is not a style choice — it is a hard
requirement. Creating a new `SnmpEngine` per operation allocates a new UDP socket that is
never released. In practice this means a script that performs 200 SNMP operations will hold
700+ open sockets, eventually triggering `OSError: Too many open files`. The shared pattern
keeps socket usage at 1–2 regardless of operation count. Any refactor that moves
`SnmpEngine()` construction inside a per-operation scope will reintroduce this bug.

Additional rules:
- All new SNMP operations must be `async` and must reuse `self.engine`.
- New public methods require a docstring with `Args:`, `Returns:`, and `Raises:` sections.
- Add inline comments for any non-obvious PySNMP API usage — the existing code sets the
  precedent, follow it.

### Changes to `albedo_mib_core.py`

- **Use `add_mib_sources()`, not `set_mib_sources()`.** `set_mib_sources()` replaces the
  entire search path, removing the standard PySNMP MIB locations. `add_mib_sources()` appends
  to the existing path, preserving built-in MIB resolution while adding the ALBEDO compiled
  directory. Using `set_mib_sources()` will silently break resolution of standard MIBs
  (SNMPv2-MIB, RFC1213-MIB, etc.).
- **MIB-specific constants belong here.** RowStatus codes, file action codes, result codes,
  pattern maps, and similar MIB-derived lookup tables must be defined in `albedo_mib_core.py`,
  not in `albedo_snmp_core.py`. This keeps the client layer free of MIB knowledge.
- Add type hints to all new public method signatures.
- Add inline comments for any non-obvious PySNMP `MibBuilder` or `MibViewController` usage.

### New MIB support

- Place the ASN.1 source file in `src/mibs/text/`. Accepted extensions: `.txt`, `.mib`,
  or no extension with a `*-MIB` suffix.
- Compile and verify: `python src/albedo_mib_core.py`. The new module must appear in the
  `✓ Success` list.
- Update `docs/ALBEDO_MIB_Reference.md` with an entry for the new module following the
  existing structure: module name, applies-to, dependencies, access level, purpose, key
  tables/objects, and typical automation use cases.
- If the new MIB introduces device-specific constants (action codes, result codes, etc.),
  add the corresponding helper methods to `AlbedoMibManager` in `albedo_mib_core.py`.

---

## Code Style

- **PEP 8** throughout. Line length limit: 100 characters.
- **Type hints** on all public method signatures. Use `str | None` union syntax (Python 3.10+
  style is acceptable; the `from __future__ import annotations` import makes it valid on 3.8+).
- **Inline comments** for any non-obvious PySNMP API usage. The bar for "non-obvious" is: if
  the behaviour differs from the PySNMP documentation or official examples, it needs a comment.
  The existing codebase documents why `add_mib_sources()` is called unconditionally, why
  `Path(__file__).parent` is used instead of a relative path, and why the walk loop uses a
  dual boundary check — new contributions should maintain this standard.
- No bare `except:` clauses. Catch the most specific exception type available; if a broad
  `except Exception` is genuinely necessary, add a comment explaining why.

---

## Submitting Changes

Standard GitHub flow:

1. Fork the repository and create a feature branch:
   `git checkout -b feature/your-descriptive-branch-name`
2. Make your changes, following the guidelines above.
3. Push the branch and open a pull request against `main`.

**Every PR description must include:**
- Which device(s) the changes were tested against (e.g. `xGenius firmware 5.12`, `Net.Time 2.4`).
- The PySNMP version used during testing (output of `pip show pysnmp | grep Version`).
- What was verified: which examples ran successfully, which SNMP operations were exercised,
  and (for `albedo_snmp_core.py` changes) confirmation that the shared `SnmpEngine` pattern
  is intact.

PRs that do not include this information will be asked for it before review.
