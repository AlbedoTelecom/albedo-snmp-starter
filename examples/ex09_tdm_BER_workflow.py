#!/usr/bin/env python3
"""
Example 09 — TDM E1 BER Workflow
==================================
End-to-end E1 BER measurement script, built from empirically confirmed
write sequences on xGenius hardware.

WORKFLOW:
  1. Ensure TDM E1 Endpoint function is active (switch from PSN if needed).
  2. Set RX test pattern (TX follows automatically via matchrx).
  3. Start monitoring (e1MonEnable = true).
  4. Read initial line results (frequency, deviation, attenuation).
  5. Poll BER metrics every SAMPLE_INTERVAL seconds for DURATION seconds.
  6. Stop monitoring (e1MonEnable = false).
  7. Print final session summary.

RESTORE:
  Stop monitoring unconditionally in the finally block.
  Pattern is not restored — the device retains whatever was written,
  which is the intended test configuration.

METRICS COLLECTED (all from ATSL-E1-MONITOR-MIB and ATSL-TDM-MONITOR-MIB):

  Anomalies (e1MonAnomaliesTable, indexed by PORT_INDEX):
    e1MonAnomaliesTse         — total bit errors (TSE count)
    e1MonAnomaliesTseRate     — BER (Real32, stored × 1000)
    e1MonAnomaliesTseSeconds  — errored seconds
    e1MonAnomaliesCrc         — CRC-4 error count
    e1MonAnomaliesFas         — FAS error count
    e1MonAnomaliesRebe        — REBE anomaly count
    e1MonAnomaliesCode        — code violation count

  Defects (e1MonDefectsTable, indexed by PORT_INDEX):
    e1MonDefectsLos / Lof / Ais / Lss
    Encoding: TruthValue — 1 = defect ACTIVE, 2 = ok (not active)

  Line (tdmMonLineTable, indexed by PORT_INDEX):
    tdmMonLineFrequency    — Hz (Real32: stored ÷ 1000)
    tdmMonLineDeviation    — ppm (Real32: stored ÷ 1000)
    tdmMonLineAttenuation  — dB (Real32: stored ÷ 1000)

CONFIRMED FIRMWARE BEHAVIOUR (xGenius, empirically validated):
  - mfFuncMode=0 on the TDM row → E1/T1 Endpoint (active TX, correct)
  - After function switch, mux slots default to pattern(1) — no mux writes needed
  - tdmPortPatternTx = 30 (matchrx) always — TX pattern follows RX setting
  - Only tdmPortPatternRx needs to be written for pattern selection
  - e1PortEnable / tdmPortEnable are readable but not writable (noAccess)
  - tdmMonPerformanceStandard is permanently noAccess on this firmware
  - e1MonEnable is the only reliable control OID for measurement start/stop
  - e1MonDefectsTable uses TruthValue (1=active, 2=ok), not a counter
  - tdmMonPerfTable (ES/SES/UAS/BBE) requires tdmMonPerformanceStandard ≠ none;
    since that OID is unwritable, performance counters are not collected here

AVAILABLE TEST PATTERNS (ITU variants recommended for E1):
  prbs11i = 1    prbs15i = 3  ← default, PRBS15 ITU (O.151)
  prbs20i = 5    prbs23i = 7

Usage:
    python ex11_tdm_ber_workflow.py <device_ip> [pattern] [duration] [port]

    pattern   — RX pattern integer value (default: 3 = prbs15i)
                or name: prbs15i, prbs23i, prbs20i, prbs11i
    duration  — measurement duration in seconds (default: 30)
    port      — port index (default: 1)

Examples:
    python ex11_tdm_ber_workflow.py 10.0.0.1
    python ex11_tdm_ber_workflow.py 10.0.0.1 prbs23i 60
    python ex11_tdm_ber_workflow.py 10.0.0.1 7 120 1
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from albedo_snmp_core import (
    MultifunctionDevice, FunctionType, PATTERN_MAP, PATTERN_NAMES,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TDM_PORT_MIB = 'ATSL-TDM-PORT-MIB'
TDM_MON_MIB  = 'ATSL-TDM-MONITOR-MIB'
E1_MON_MIB   = 'ATSL-E1-MONITOR-MIB'

# TruthValue encoding used by e1MonDefectsTable and e1MonEnable
MON_TRUE  = 1   # defect active / monitoring on
MON_FALSE = 2   # defect ok    / monitoring off

SAMPLE_INTERVAL = 5   # seconds between metric reads

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_pattern(arg: str) -> int:
    """Accept either a pattern name ('prbs15i') or an integer ('3')."""
    if arg in PATTERN_MAP:
        return PATTERN_MAP[arg]
    try:
        v = int(arg)
        if v not in PATTERN_NAMES:
            print(f"Warning: pattern value {v} is not in the known pattern table.")
        return v
    except ValueError:
        print(f"Unknown pattern '{arg}', using default prbs15i (3).")
        return 3


DEVICE_IP  = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.100'
PATTERN_RX = _parse_pattern(sys.argv[2]) if len(sys.argv) > 2 else 3   # prbs15i
DURATION   = int(sys.argv[3])           if len(sys.argv) > 3 else 30
PORT_INDEX = int(sys.argv[4])           if len(sys.argv) > 4 else 1

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def real32(val) -> float | None:
    """Convert a Real32 stored integer to its display value (÷ 1000)."""
    if val is None:
        return None
    try:
        return int(val) / 1000.0
    except (ValueError, TypeError):
        return None


def fmt_real32(val, unit: str = '', precision: int = 3) -> str:
    v = real32(val)
    if v is None:
        return f'? {unit}'.strip()
    return f'{v:.{precision}f} {unit}'.strip()


def fmt_defect(val) -> str:
    """TruthValue: 1 = ACTIVE, 2 = ok."""
    if val is None:
        return '?'
    return 'ACTIVE' if int(val) == MON_TRUE else 'ok'


def fmt_count(val) -> str:
    return '?' if val is None else str(int(val))


def fmt_ber(val) -> str:
    """
    Format e1MonAnomaliesTseRate for display.

    Real32 (DISPLAY-HINT "d-3"): stored integer / 1000 = displayed value.
    Resolution is 0.001 -- any BER below 0.0005 stores as integer 0.
    A result of 0 means the rate is below display resolution, not zero errors.
    Use TSE count and errored seconds as reliable indicators at low rates.
    """
    if val is None:
        return '?'
    try:
        iv = int(val)
    except (ValueError, TypeError):
        return '?'
    if iv == 0:
        return '< 0.001  (below resolution -- use TSE count)'
    return f'{iv / 1000.0:.3f}'

# ---------------------------------------------------------------------------
# Metric readers
# ---------------------------------------------------------------------------

async def read_line(device: MultifunctionDevice) -> None:
    """Print tdmMonLineTable results for PORT_INDEX."""
    freq  = await device.get(TDM_MON_MIB, 'tdmMonLineFrequency',   PORT_INDEX)
    dev   = await device.get(TDM_MON_MIB, 'tdmMonLineDeviation',   PORT_INDEX)
    atten = await device.get(TDM_MON_MIB, 'tdmMonLineAttenuation', PORT_INDEX)
    print(f"  Frequency  : {fmt_real32(freq,  'Hz')}")
    print(f"  Deviation  : {fmt_real32(dev,   'ppm')}")
    print(f"  Attenuation: {fmt_real32(atten, 'dB')}")


async def read_sample(device: MultifunctionDevice, n: int) -> None:
    """Print one sample of BER anomalies and defect flags."""
    tse     = await device.get(E1_MON_MIB, 'e1MonAnomaliesTse',        PORT_INDEX)
    tse_r   = await device.get(E1_MON_MIB, 'e1MonAnomaliesTseRate',    PORT_INDEX)
    tse_s   = await device.get(E1_MON_MIB, 'e1MonAnomaliesTseSeconds', PORT_INDEX)
    crc     = await device.get(E1_MON_MIB, 'e1MonAnomaliesCrc',        PORT_INDEX)
    fas     = await device.get(E1_MON_MIB, 'e1MonAnomaliesFas',        PORT_INDEX)
    los     = await device.get(E1_MON_MIB, 'e1MonDefectsLos',          PORT_INDEX)
    lof     = await device.get(E1_MON_MIB, 'e1MonDefectsLof',          PORT_INDEX)
    ais     = await device.get(E1_MON_MIB, 'e1MonDefectsAis',          PORT_INDEX)
    lss     = await device.get(E1_MON_MIB, 'e1MonDefectsLss',          PORT_INDEX)

    print(f"\n  [Sample {n}]")
    print(f"  Defects : LOS={fmt_defect(los)}  LOF={fmt_defect(lof)}"
          f"  AIS={fmt_defect(ais)}  LSS={fmt_defect(lss)}")
    print(f"  TSE     : {fmt_count(tse):>10}  BER={fmt_ber(tse_r)}"
          f"  errored seconds={fmt_count(tse_s)}")
    print(f"  CRC-4   : {fmt_count(crc):>10}  FAS={fmt_count(fas)}")


async def read_summary(device: MultifunctionDevice) -> None:
    """Print final totals from both anomaly and line tables."""
    print("\n=== Final summary ===")

    tse   = await device.get(E1_MON_MIB, 'e1MonAnomaliesTse',        PORT_INDEX)
    tse_r = await device.get(E1_MON_MIB, 'e1MonAnomaliesTseRate',    PORT_INDEX)
    tse_s = await device.get(E1_MON_MIB, 'e1MonAnomaliesTseSeconds', PORT_INDEX)
    crc   = await device.get(E1_MON_MIB, 'e1MonAnomaliesCrc',        PORT_INDEX)
    fas   = await device.get(E1_MON_MIB, 'e1MonAnomaliesFas',        PORT_INDEX)
    rebe  = await device.get(E1_MON_MIB, 'e1MonAnomaliesRebe',       PORT_INDEX)
    code  = await device.get(E1_MON_MIB, 'e1MonAnomaliesCode',       PORT_INDEX)

    freq  = await device.get(TDM_MON_MIB, 'tdmMonLineFrequency',     PORT_INDEX)
    dev   = await device.get(TDM_MON_MIB, 'tdmMonLineDeviation',     PORT_INDEX)
    atten = await device.get(TDM_MON_MIB, 'tdmMonLineAttenuation',   PORT_INDEX)

    print(f"\n  Pattern    : {PATTERN_NAMES.get(PATTERN_RX, str(PATTERN_RX))}"
          f"  (port {PORT_INDEX})")
    print(f"\n  BER anomalies:")
    print(f"    TSE (bit errors)  : {fmt_count(tse):>12}"
          f"  BER = {fmt_ber(tse_r)}")
    print(f"    Errored seconds   : {fmt_count(tse_s):>12}")
    print(f"    CRC-4 errors      : {fmt_count(crc):>12}")
    print(f"    FAS errors        : {fmt_count(fas):>12}")
    print(f"    REBE anomalies    : {fmt_count(rebe):>12}")
    print(f"    Code violations   : {fmt_count(code):>12}")
    print(f"\n  Line (final):")
    print(f"    Frequency         : {fmt_real32(freq,  'Hz')}")
    print(f"    Deviation         : {fmt_real32(dev,   'ppm')}")
    print(f"    Attenuation       : {fmt_real32(atten, 'dB')}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    start = datetime.now()

    print("=" * 60)
    print("  Example 09 — TDM E1 BER Workflow")
    print("=" * 60)
    print(f"  Device   : {DEVICE_IP}")
    print(f"  Port     : {PORT_INDEX}")
    print(f"  Pattern  : {PATTERN_RX} ({PATTERN_NAMES.get(PATTERN_RX, 'unknown')})")
    print(f"  Duration : {DURATION}s  (sample every {SAMPLE_INTERVAL}s)")
    print(f"  Started  : {start.strftime('%Y-%m-%d %H:%M:%S')}")

    async with MultifunctionDevice(DEVICE_IP) as device:

        try:
            # ----------------------------------------------------------
            # Step 1: Ensure TDM E1 Endpoint is active.
            # ----------------------------------------------------------
            print("\n=== Step 1: Ensure TDM function active ===")
            if await device.is_multifunction():
                ok = await device.ensure_function(FunctionType.TDM_E1T1_ENDPOINT)
                if not ok:
                    print("  ERROR: Could not switch to TDM. Aborting.")
                    return
                active = await device.get_active_function()
                print(f"  Active function: {active.name if active else 'unknown'}")
            else:
                print("  Not a multifunction device — assuming TDM active.")

            # ----------------------------------------------------------
            # Step 2: Set RX pattern. TX follows via matchrx(30).
            # ----------------------------------------------------------
            print(f"\n=== Step 2: Set RX pattern = "
                  f"{PATTERN_RX} ({PATTERN_NAMES.get(PATTERN_RX, '?')}) ===")
            ok = await device.set(
                TDM_PORT_MIB, 'tdmPortPatternRx', PATTERN_RX, PORT_INDEX)
            readback = await device.get(
                TDM_PORT_MIB, 'tdmPortPatternRx', PORT_INDEX)
            confirmed = (readback is not None and int(readback) == PATTERN_RX)
            print(f"  SET: {'✓' if ok else '✗'}  "
                  f"readback: {readback}  "
                  f"{'✓' if confirmed else '✗ mismatch'}")
            if not confirmed:
                print("  WARNING: Pattern write not confirmed. "
                      "Continuing anyway — device may use its own default.")

            # ----------------------------------------------------------
            # Step 3: Start monitoring.
            # ----------------------------------------------------------
            print("\n=== Step 3: Start monitoring ===")
            ok = await device.set(E1_MON_MIB, 'e1MonEnable', MON_TRUE, 0)
            print(f"  e1MonEnable → true: {'✓' if ok else '✗'}")
            await asyncio.sleep(1)   # allow analyser to lock

            # ----------------------------------------------------------
            # Step 4: Initial line results.
            # ----------------------------------------------------------
            print(f"\n=== Step 4: Line results (port {PORT_INDEX}) ===")
            await read_line(device)

            # ----------------------------------------------------------
            # Step 5: Sample loop.
            # ----------------------------------------------------------
            print(f"\n=== Step 5: Sampling for {DURATION}s ===")
            elapsed = 0
            sample  = 0
            while elapsed < DURATION:
                await asyncio.sleep(SAMPLE_INTERVAL)
                elapsed += SAMPLE_INTERVAL
                sample  += 1
                await read_sample(device, sample)

            # ----------------------------------------------------------
            # Step 6: Stop monitoring.
            # ----------------------------------------------------------
            print("\n=== Step 6: Stop monitoring ===")
            ok = await device.set(E1_MON_MIB, 'e1MonEnable', MON_FALSE, 0)
            print(f"  e1MonEnable → false: {'✓' if ok else '✗'}")

            # ----------------------------------------------------------
            # Step 7: Final summary.
            # ----------------------------------------------------------
            await read_summary(device)

        finally:
            # Unconditional: ensure monitoring is off.
            await device.set(E1_MON_MIB, 'e1MonEnable', MON_FALSE, 0)

            end     = datetime.now()
            elapsed = (end - start).total_seconds()
            print(f"\n  Finished: {end.strftime('%Y-%m-%d %H:%M:%S')}"
                  f"  (total: {elapsed:.0f}s)")


if __name__ == '__main__':
    asyncio.run(main())