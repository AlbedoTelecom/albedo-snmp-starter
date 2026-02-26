# ALBEDO Telecom SNMP MIB Reference
### For Python Developers Using PySNMP

---

## Overview

All ALBEDO Telecom MIB objects are rooted at OID **`1.3.6.1.4.1.39412`** (IANA enterprise 39412), defined in `ATSL-MIB` as the `atsl` node. Beneath it, two branches carry the operational MIBs: **`atslGeneral`** (`atsl.1`) contains all generic test-and-measurement MIBs (E1/T1, PSN/Ethernet, file management, synchronization, etc.) and is shared across device families; **`atslSpecial`** (`atsl.2`) is reserved for device-specific extensions. A third branch, **`atslProduct`** (`atsl.4`), hosts product-line-specific trees — notably the Net.Time clock sub-tree (`atslNetTime`). Because nearly every MIB in the set imports custom textual conventions (`TableIndex`, `Real32`, `RatioPercentage`, `Word32`, etc.) from `ATSL-MIB`, that root MIB **must always be compiled first** by PySNMP's `MibBuilder`. Many interface-specific MIBs additionally depend on `ATSL-TDM-PORT-MIB` for shared type definitions (`FrameType`, `TimeSlotUse`, `ABCD`, `ConnectorType`), and all file-class MIBs depend on `ATSL-FILEMGR-MIB` for the `fileClasses` subtree node and the `FileAction`/`FileOpsResult` textual conventions.

---

## 1. System & Device Management

---

### `ATSL-MIB.txt`
**Module name:** `ATSL-MIB` *(root — imported by all other modules)*

**Applies to:** xGenius / Net.Time / both

**Depends on:** `SNMPv2-SMI`, `SNMPv2-TC` (standard MIBs only)

**Access:** Mixed (mostly defines types; the `atsl` node itself is read-only)

**Purpose:** Defines the ALBEDO OID root, the `atslGeneral`/`atslSpecial`/`atslProduct` sub-trees, and all shared textual conventions used across the entire MIB set.

**Key tables / objects:**
- `atslGeneral` — Parent OID node for all generic test MIBs; needed as the import anchor in every other module.
- `atslProduct` — Parent OID node for product-specific MIBs (Net.Time lives here).
- `TableIndex` — Unsigned integer TC used as table row index in all ALBEDO tables.
- `Real32` — Fixed-point decimal TC (`Integer32` scaled by 1000); used for frequencies, delays, levels.
- `RatioPercentage` — Percentage TC; used for BER rates, SLA metrics, and performance ratios.
- `Word32` / `Word16` — Hex-display integer TCs used for VLAN IDs, MPLS labels, bitmasks.
- `TestPattern` / `Encapsulation` / `MplsLabel` — Enumeration TCs used across generator MIBs.

**Typical automation use cases:**
1. Compile this MIB first in your `MibBuilder` `addMibSources()` call; all other ALBEDO modules fail to load without it.
2. Use `ObjectIdentity('ATSL-MIB', 'atslGeneral')` to walk the entire general MIB subtree for discovery.
3. Decode `Real32` values in Python by dividing the raw integer by 1000 (e.g., `3750` → `3.750`).

---

### `ATSL-REGISTRATION-MIB.txt`
**Module name:** `ATSL-REGISTRATION-MIB`

**Applies to:** xGenius / Net.Time / both

**Depends on:** `ATSL-MIB`

**Access:** Read-only (purely structural, no writable objects)

**Purpose:** Defines OID registration nodes for each ALBEDO product family, providing stable sysObjectID anchors for device identification.

**Key tables / objects:**
- `atslPDHReg` — Registration subtree for PDH testers (AT-2048, AT.One).
- `atslEthernetReg` — Registration subtree for Ethernet testers (Ether.Genius, Ether10.Genius, xGenius variants).
- `atslClockReg` / `atslNetTimeReg` — Registration subtree for Net.Time clock devices.
- `atslNetworkReg` — Registration subtree for network analysis instruments.

**Typical automation use cases:**
1. Retrieve the device's `sysObjectID` via standard `SNMPv2-MIB` and compare against nodes in this MIB to identify the device model programmatically.
2. Use the registered OID as a key in a dispatch table to load the appropriate MIB subset for a discovered device.

---

### `ATSL-SYSTEM-MIB.txt`
**Module name:** `ATSL-SYSTEM-MIB`

**Applies to:** xGenius / Net.Time / both

**Depends on:** `ATSL-MIB`

**Access:** Mixed (identity/license/inventory read-only; `sysCmdRestoreDft` and `sysCmdSaveStartup` are writable)

**Purpose:** Exposes device identity (product name, serial number, firmware/software/hardware versions), software license status, hardware inventory, GPS location coordinates, and system-level commands.

**Key tables / objects:**
- `sysIDproduct` — Product model name string (e.g., `"xGenius"`).
- `sysIDserialNumber` — Unit serial number; useful as a unique device key.
- `sysIDswVersion` / `sysIDhwVersion` / `sysIDfwVersion` — Software, hardware, and firmware version strings.
- `atslSysLicTable` — Per-feature license table with `sysLicDescription`, `sysLicStatus` (active/deactivated), `sysLicStartDate`, `sysLicFinishDate`.
- `atslSysHWInvTable` — Hardware inventory table listing installed modules with type, slot, and attributes.
- `sysLocLongitude` / `sysLocLatitude` / `sysLocSite` — GPS coordinates and site name (available on GNSS-equipped units).
- `sysCmdRestoreDft` — Write to trigger a factory-default restore.
- `sysCmdSaveStartup` — Write to persist current configuration as startup configuration.

**Typical automation use cases:**
1. GET `sysIDproduct`, `sysIDserialNumber`, and `sysIDswVersion` at connection time to populate an inventory database and gate against firmware-version-dependent behavior.
2. Walk `atslSysLicTable` to verify that required feature licenses (e.g., RFC 2544, PTP) are active before starting a test suite.
3. Poll `sysLocLatitude` / `sysLocLongitude` to confirm GPS lock on timing devices before accepting synchronization results.

---

## 2. TDM Testing (E1 / T1 / Datacom / VF / C37.94)

---

### `ATSL-TDM-PORT-MIB.txt`
**Module name:** `ATSL-TDM-PORT-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Defines shared TDM textual conventions (`FrameType`, `TimeSlotUse`, `ABCD`, `ConnectorType`, `TdmInterface`, `OperationMode`) and the generic mode-selection table for all TDM interfaces; it is the type-definition dependency for all E1, T1, Datacom, and C37.94 port MIBs.

**Key tables / objects:**
- `tdmPortModeTable` — Selects the operating mode for each TDM port (e.g., `e1Endpoint`, `e1Monitor`, `t1Endpoint`, `datacomEndpoint`, `datacomMonitor`). **This is the primary mode-switching table for TDM ports.**
- `tdmPortPatternTable` — Configures the test pattern generator/analyzer (PRBS pattern type, insertion rate, channel selection).
- `FrameType` TC — Enumerates E1/T1 frame structures (`pcm31`, `pcm31c`, `pcm30`, `pcm30c`, `esf`, `sf`, `unframed`, etc.).
- `OperationMode` TC — Enumerates all TDM operation modes; used in `mfFuncMode` via ATSL-MULTIFUNCTION-MIB.

**Typical automation use cases:**
1. SET `tdmPortModeTable` rows to configure a port as `e1Endpoint` before running an E1 BER test.
2. Use the `OperationMode` enumeration values when setting `mfFuncMode` in a multifunction device to switch between TDM and PSN functions.
3. Configure `tdmPortPatternTable` to select a PRBS-15 pattern before starting a TSE error measurement.

---

### `ATSL-E1-PORT-MIB.txt`
**Module name:** `ATSL-E1-PORT-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`, `ATSL-TDM-PORT-MIB`

**Access:** Mixed

**Purpose:** Configures all physical and framing parameters for a 2048 kb/s E1 test port, including line code, connector type, clock source, frequency offset, TX/RX frame structure, time-slot multiplexer/demultiplexer mapping, CAS signalling bits, and the NFAS content for CRC-4 frames.

**Key tables / objects:**
- `e1PortEnable` — Global TX enable/disable for E1 generation.
- `e1AddDropSource` — Selects the external add/drop source (`datacom`, `g703e0`) for time-slot pass-through testing.
- `e1PortLineTable` — Physical layer settings: `e1PortLineConnector` (BNC/RJ45), `e1PortLineConnectionMode` (endpoint, monitor-20dB/25dB/30dB, highZ), `e1PortLineTxCode`/`e1PortLineRxCode` (HDB3/AMI), `e1PortLineTxClock` (synthesized/recovered), `e1PortLineFrequencyDeviation` (ppm offset for stress testing).
- `e1PortFrameTable` — Frame structure: `e1PortFrameTxStructure` / `e1PortFrameRxStructure` (PCM30, PCM30C, PCM31, PCM31C, unframed); CAS spare bits.
- `e1PortMuxTable` — 32-row table assigning a data source to each TX time slot (pattern generator, tone, external port, loopback from RX).
- `e1PortDemuxTable` — 32-row table assigning a destination for each RX time slot (pattern analyzer, tone analyzer, external port).
- `e1PortCasTable` — ABCD signalling bit configuration per CAS channel.

**Typical automation use cases:**
1. SET `e1PortLineTable` to configure HDB3 coding, recovered TX clock, and endpoint connection mode before an E1 pass-through test.
2. Configure `e1PortFrameTable` with `pcm31c` and then write `e1PortMuxTable` to route specific time slots to the pattern generator.
3. Apply a frequency deviation via `e1PortLineFrequencyDeviation` to stress-test a network element's clock tolerance.

---

### `ATSL-E1-MONITOR-MIB.txt`
**Module name:** `ATSL-E1-MONITOR-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`, `ATSL-TDM-PORT-MIB`

**Access:** Mixed (`e1MonEnable` and occupancy time-slot selector are writable; all counters and status are read-only)

**Purpose:** Retrieves E1 monitoring results: anomaly counters (code errors, FAS, CRC-4, REBE, MFAS, TSE), persistent defect indicators (LOS, AIS, LOF, RAI, CRC-LOM, CAS-LOM, MAIS, MRAI, LSS, All-0, All-1, Slip), per-time-slot occupancy/audio analysis, and raw TS0/CAS multiframe content.

**Key tables / objects:**
- `e1MonEnable` — Starts/stops E1 monitoring on all blocks.
- `e1MonAnomaliesTable` — Per-block anomaly counters: `e1MonAnomaliesCode`, `e1MonAnomaliesFas`, `e1MonAnomaliesCrc`, `e1MonAnomaliesRebe`, `e1MonAnomaliesMfas`, `e1MonAnomaliesTse`; each with a `*Rate` (%) and `*Seconds` companion.
- `e1MonDefectsTable` — Per-block defect booleans + elapsed seconds: LOS, AIS, LOF, RAI, CRC-LOM, CAS-LOM, MAIS, MRAI, LSS, All-0, All-1, Slip.
- `e1MonOccupancyTable` — Per-time-slot signal analysis: `e1MonOccupancyTimeSlot` (write to select), `e1MonOccupancyLevel` (dBm0), `e1MonOccupancyFrequency` (Hz), min/max/avg PCM code.
- `e1MonMultiframeTable` — CAS multiframe spare bits readout.
- `e1MonCrc4Table` — Raw TS0 byte per frame in a CRC-4 multiframe (indexed by block + frame number).
- `e1MonCasTable` — ABCD signalling bits per CAS channel (indexed by block + channel).

**Typical automation use cases:**
1. Poll `e1MonAnomaliesTable` after a test run to collect TSE count, CRC-4 errors, and code error rate for BER analysis.
2. Monitor `e1MonDefectsTable.e1MonDefectsLos` and `e1MonDefectsAis` in a loop to detect link-down events during acceptance testing.
3. Write `e1MonOccupancyTimeSlot` and then read `e1MonOccupancyLevel` / `e1MonOccupancyFrequency` to verify voice channel content per time slot.

---

### `ATSL-T1-PORT-MIB.txt`
**Module name:** `ATSL-T1-PORT-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`, `ATSL-TDM-PORT-MIB`

**Access:** Mixed

**Purpose:** Configures 1544 kb/s T1 test port physical and framing parameters — analogous to `ATSL-E1-PORT-MIB` but for the North American T1 interface, supporting ESF and SF/D4 framing, AMI/B8ZS line codes, and a 24-time-slot MUX/DEMUX.

**Key tables / objects:**
- `t1PortLineTable` — Physical settings: connector, line code (AMI/B8ZS), TX clock source (synthesized/recovered), frequency offset.
- `t1PortFrameTable` — Frame structure: TX/RX structure (ESF, SF/D4, unframed); yellow alarm bit.
- `t1PortMuxTable` — 24-row TX time-slot source assignment table.
- `t1PortDemuxTable` — 24-row RX time-slot destination assignment table.

**Typical automation use cases:**
1. Configure `t1PortFrameTable` for ESF framing and `t1PortLineTable` for B8ZS before a T1 BER test.
2. Use `t1PortMuxTable` to route specific DS0 channels to the pattern generator for targeted time-slot testing.

> **Distinction vs. ATSL-E1-PORT-MIB:** T1-specific — 1.544 Mb/s rate, 24 time slots, B8ZS/AMI codes, ESF/SF framing. E1-PORT-MIB covers 2.048 Mb/s, 32 time slots, HDB3/AMI, PCM30/PCM31 framing.

---

### `ATSL-T1-MONITOR-MIB.txt`
**Module name:** `ATSL-T1-MONITOR-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`, `ATSL-TDM-PORT-MIB`

**Access:** Mixed

**Purpose:** Retrieves T1 monitoring results — anomaly counters, defect status, per-DS0 occupancy, and CAS/robbed-bit signalling readout for T1 interfaces.

**Key tables / objects:**
- `t1MonAnomaliesTable` — Anomaly counters: FAS, CRC-6 (ESF), code errors, TSE; with rate and seconds variants.
- `t1MonDefectsTable` — Defect booleans + elapsed seconds: LOS, AIS, LOF, RAI, LSS, All-0, All-1, Slip.
- `t1MonOccupancyTable` — Per-DS0 level, frequency, and PCM code statistics.
- `t1MonCasTable` — ABCD robbed-bit signalling per DS0 channel.

**Typical automation use cases:**
1. Poll `t1MonAnomaliesTable` to retrieve ESF CRC-6 errors and TSE counts after a T1 test run.
2. Check `t1MonDefectsTable.t1MonDefectsLos` as a precondition before starting timed measurements.

> **Distinction vs. ATSL-E1-MONITOR-MIB:** T1-specific — CRC-6 instead of CRC-4, 24 DS0 channels, different FAS/framing anomaly definitions.

---

### `ATSL-TDM-MONITOR-MIB.txt`
**Module name:** `ATSL-TDM-MONITOR-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed (delay offset configuration writable; all results read-only)

**Purpose:** Provides cross-interface TDM performance and delay measurements — ITU-T G.826/M.2100 performance parameters (ES, SES, UAS, BBE, DM), round-trip delay, one-way forward and reverse delay, asymmetry measurements, and received signal attenuation and frequency deviation — applicable to E1, T1, and C37.94 interfaces.

**Key tables / objects:**
- `tdmMonEnable` — Starts/stops TDM monitoring.
- `tdmMonPerformanceStandard` — Selects the ITU-T performance standard (G.826, M.2100, etc.) for ES/SES/UAS classification.
- `tdmMonDelayEnable` — Enables the one-way delay measurement engine.
- `tdmMonDelayMode` — Selects delay measurement mode (RTD / one-way).
- `tdmMonDelayRtdOffset` / `tdmMonDelayForwardOffset` / `tdmMonDelayReverseOffset` — Cable offset corrections (in µs) for precise delay calculation.
- `tdmMonLineTable` — Per-block signal quality: `tdmMonLineAttenuation` (dB, current and max), `tdmMonLineFrequency` (Hz), `tdmMonLineDeviation` (ppm, current and max).
- `tdmMonPerfTable` — G.826 performance counters: `tdmMonPerfEsNear`/`Far`, `tdmMonPerfSesNear`/`Far`, `tdmMonPerfUasNear`/`Far`, `tdmMonPerfBbeNear`/`Far`, `tdmMonPerfDmNear`/`Far`; each with a `*Percent` companion.
- `tdmMonRtdTable` — Round-trip delay results: `tdmMonRtdDelayCurrent`, `tdmMonRtdDelayMin`, `tdmMonRtdDelayMax`.
- `tdmMonDelayTable` — One-way delay results: forward, reverse, RTD, and asymmetry — each with current, min, and max values; plus `tdmMonDelayRemoteHost` identifying the far-end.

**Typical automation use cases:**
1. Poll `tdmMonDelayTable` to retrieve forward, reverse, and asymmetry delay values during a one-way delay measurement campaign over E1.
2. Collect `tdmMonPerfTable.tdmMonPerfUasNear` and `tdmMonPerfSesNear` at test end to evaluate ITU-T G.826 performance compliance.
3. Read `tdmMonLineTable.tdmMonLineFrequency` and `tdmMonLineDeviation` to verify clock accuracy on a received E1 signal.

---

### `ATSL-TDM-IMPAIRMENT-MIB.txt`
**Module name:** `ATSL-TDM-IMPAIRMENT-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Injects controlled anomalies and defects into a transmitted TDM stream to stress-test network equipment — allows insertion of error bursts, AIS, pattern inversions, and loss-of-signal conditions.

**Key tables / objects:**
- `tdmImpAnomaliesTable` — Configures anomaly injection: type (FAS, code, CRC, TSE), rate, and burst mode.
- `tdmImpDefectsTable` — Configures persistent defect injection: type (AIS, LOS), duration.

**Typical automation use cases:**
1. SET `tdmImpAnomaliesTable` to inject a fixed TSE rate while simultaneously reading `e1MonAnomaliesTable` to validate the DUT's anomaly detection threshold.
2. Use `tdmImpDefectsTable` to inject AIS and verify that the DUT raises the correct alarm.

---

### `ATSL-DATACOM-PORT-MIB.txt`
**Module name:** `ATSL-DATACOM-PORT-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Configures physical parameters for synchronous and asynchronous datacom interfaces (V.24/V.28, V.35, V.36, EIA-530, EIA-530A, X.21/V.11, G.703 co-directional), including DTE/DCE emulation, bit rate, TX clock source, and V.24-specific async framing parameters.

**Key tables / objects:**
- `dataPortEnable` — Global TX enable/disable.
- `dataPortLineTable` — Per-block settings: `dataPortLineEmulationMode` (DTE/DCE), `dataPortLineOperationMode` (synchronous/asynchronous), `dataPortLineTdClockCircuit` (TC/TTC), `dataPortLineTxClock` (synthesized/recovered), `dataPortLineTxClockOffset` (ppm), `dataPortLineRate` (Nx64, Nx56, user, or fixed), `dataPortLineRateNFactor`/`dataPortLineRateUser`.
- Async-only settings: `dataPortLineDataBits` (5–8), `dataPortLineStopBits` (1/1.5/2), `dataPortLineParity` (none/even/odd), `dataPortLineInterwordTxGap`.

**Typical automation use cases:**
1. SET `dataPortLineEmulationMode` to `dce` and `dataPortLineRate` to `kbpsnx64` with `dataPortLineRateNFactor=2` to generate a 128 kb/s synchronous V.35 test signal.
2. Configure V.24 async parameters (`dataPortLineDataBits`, `dataPortLineStopBits`, `dataPortLineParity`) for asynchronous serial interface testing.

---

### `ATSL-DATACOM-MONITOR-MIB.txt`
**Module name:** `ATSL-DATACOM-MONITOR-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed (`dataMonEnable` and `dataMonMapCircuitState` for controllable circuits are writable; all statistics read-only)

**Purpose:** Retrieves monitoring statistics and real-time circuit state for synchronous/asynchronous datacom interfaces (V.24, V.35, V.36, EIA-530, EIA-530A, X.21, G.703 co-directional), including anomaly counters, defect indicators, and a live circuit map showing signal direction, activity, and state for every interface pin.

**Key tables / objects:**
- `dataMonEnable` — Starts/stops datacom monitoring.
- `dataMonAnomaliesTable` — Anomaly counters: `dataMonAnomaliesFrame` (V.24 async framing), `dataMonAnomaliesParity`, `dataMonAnomaliesTse`; with rate and seconds companions.
- `dataMonDefectsTable` — Defect booleans + elapsed seconds: LOS, LOC (Loss of Clock), LSS, All-0, All-1, Slip, AIS (G.703 co-dir).
- `dataMonMapTable` — Live circuit map indexed by `[interfaceIndex, circuitIndex]`: `dataMonMapSignal` (e.g., "TD", "RD", "RTS"), `dataMonMapCircuitDirection` (fromDTE/fromDCE), `dataMonMapCircuitActivity` (idle/active), `dataMonMapCircuitState` (zero/one/on/off); `dataMonMapCircuitState` is writable for controllable control circuits.

**Typical automation use cases:**
1. Walk `dataMonMapTable` to display a real-time pin status diagram of a V.35 interface during loopback testing.
2. Poll `dataMonDefectsTable.dataMonDefectsLoc` to detect clock failures on a synchronous EIA-530 link.
3. Write `dataMonMapCircuitState` on an RTS circuit to simulate a hardware handshake event during DTE emulation testing.

---

### `ATSL-C3794-PORT-MIB.txt`
**Module name:** `ATSL-C3794-PORT-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`, `ATSL-TDM-PORT-MIB`

**Access:** Mixed

**Purpose:** Configures IEEE C37.94 optical test ports for N×64 kb/s (N=1..12) teleprotection interface testing, including optical transmitter safety control, TX clock source, frequency deviation, and frame/payload size selection.

**Key tables / objects:**
- `c3794PortEnable` — Global TX enable/disable for C37.94 generation.
- `c3794PortLineTable` — Optical layer: `c3794PortLineEnable`, `c3794PortLineLaserOn` (safety switch), `c3794PortLineTxClock` (synthesized/recovered), `c3794PortLineFrequencyDeviation` (ppm).
- `c3794PortFrameTable` — Frame and payload: `c3794PortFrameStructure` (C37.94 framed or unframed), `c3794PortFrameTxTimeSlots` (1–12, i.e., 64–768 kb/s payload).

**Typical automation use cases:**
1. SET `c3794PortLineLaserOn` to `true` only during active test runs to comply with optical safety procedures.
2. Configure `c3794PortFrameTxTimeSlots` = 12 for maximum 768 kb/s payload C37.94 testing of teleprotection relay equipment.

---

### `ATSL-C3794-MONITOR-MIB.txt`
**Module name:** `ATSL-C3794-MONITOR-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed (`c3794MonEnable` writable; all results read-only)

**Purpose:** Retrieves IEEE C37.94 monitoring results: code errors, FAS errors, TSE bit errors (anomalies), and persistent defects (LOS, AIS, ACT — loss of optical activity, RDI, LSS, All-0, All-1, Slip) for teleprotection interface testing.

**Key tables / objects:**
- `c3794MonEnable` — Starts/stops C37.94 monitoring.
- `c3794MonAnomaliesTable` — Per-block counters: `c3794MonAnomaliesCode`, `c3794MonAnomaliesFas`, `c3794MonAnomaliesTse`; each with rate and seconds companions.
- `c3794MonDefectsTable` — Per-block defect booleans + elapsed seconds: LOS, AIS, ACT (no optical transitions — idle channel), RDI, LSS, All-0, All-1, Slip.

**Typical automation use cases:**
1. Poll `c3794MonAnomaliesTable.c3794MonAnomaliesTse` and `c3794MonAnomaliesFas` to measure transmission quality on a C37.94 link between protection relays.
2. Check `c3794MonDefectsTable.c3794MonDefectsAct` to verify the optical channel is not idle (ACT defect absent) before logging results.

---

### `ATSL-VF-MIB.txt`
**Module name:** `ATSL-VF-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Controls voice-frequency (VF) testing on analogue ports — tone generation at configurable frequency and level, analogue signal measurement (level in dBm0, frequency in Hz, noise), and speaker/headset routing.

**Key tables / objects:**
- `vfTestToneGeneratorTable` — Configures tone generator: frequency (Hz), level (dBm0), and on/off state.
- `vfTestAnalogTable` — Analogue measurement results: received level (dBm0), frequency (Hz), noise level (psophometric weighting).
- `vfTestSpeakerTable` — Routes a selected time slot or tone to the analogue audio output.

**Typical automation use cases:**
1. SET `vfTestToneGeneratorTable` to inject a 1004 Hz tone at 0 dBm0 into a selected E1 time slot for transmission level testing.
2. Read `vfTestAnalogTable` level and frequency after injecting a tone to verify the analogue audio path attenuation.

---

### `ATSL-TDR-MIB.txt`
**Module name:** `ATSL-TDR-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Controls and retrieves results from a Time-Domain Reflectometer (TDR) function for cable fault location — reports fault distance, reflection coefficient, and cable type.

**Key tables / objects:**
- `tdrTLTable` — TDR transmission-line measurement table: measured fault distance, reflection magnitude, and cable segment results.

**Typical automation use cases:**
1. Trigger a TDR sweep and poll `tdrTLTable` to retrieve cable fault distance for physical-layer troubleshooting on copper pairs.

---

## 3. PSN / Ethernet Testing

---

### `ATSL-PSN-PORT-MIB.txt`
**Module name:** `ATSL-PSN-PORT-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Configures physical Ethernet port parameters — port speed, autonegotiation, duplex mode, and SFP/optical interface settings.

**Key tables / objects:**
- `psnPortCfgPhyTable` — Per-port physical layer settings: speed (10M/100M/1G/10G), autoneg enable, duplex mode, SFP type.

**Typical automation use cases:**
1. SET `psnPortCfgPhyTable` to force a specific speed and disable autonegotiation before starting an RFC 2544 test.

---

### `ATSL-PSN-GENERATOR-MIB.txt`
**Module name:** `ATSL-PSN-GENERATOR-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Configures the Ethernet/IP/MPLS traffic generator — sets stream mode, encapsulation, MAC/IP/VLAN addressing, traffic rate and bandwidth, payload pattern, and loopback responder behavior.

**Key tables / objects:**
- `psnGenEnable` / `psnGenMode` / `psnGenTrafficControl` — Global generator enable, mode selection (endpoint/monitor/loopback), and traffic start/stop.
- `psnGenModeTable` — Per-stream network identity: `psnGenModeMacLocal`, `psnGenModeEncapsulationLocal`, VLAN IDs, DHCP enable, IPv4 static address/mask/gateway/DNS, and leased IP address readback.
- `psnGenPatternTable` — Test pattern type and insertion configuration per stream.
- `psnGenEthTable` — Ethernet framing per stream: src/dst MAC, EtherType, VLAN, 802.1ad (QinQ) settings.
- `psnGenIpMplsTable` — MPLS label stack configuration.
- `psnGenIpTable` — IP layer settings: src/dst IP, TTL, DSCP, protocol.
- `psnGenBandwidthTable` — Traffic rate/bandwidth per stream: rate in Mbps, frame size, CIR/EIR.
- `psnGenPayloadTable` — Payload content and size distribution settings.
- `psnGenLoopbackTable` — Loopback responder configuration (swap src/dst MAC, swap IP, etc.).

**Typical automation use cases:**
1. Configure `psnGenModeTable` with a static IP address and then SET `psnGenBandwidthTable` to define a 100 Mbps UDP stream before starting an SLA measurement.
2. Enable loopback mode via `psnGenLoopbackTable` on the remote unit, then start the generator to perform an end-to-end delay test.
3. Write `psnGenTrafficControl` to toggle traffic bursts during an RFC 2544 back-to-back test.

---

### `ATSL-PSN-MONITOR-MIB.txt`
**Module name:** `ATSL-PSN-MONITOR-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed (`psnMonEnable` writable; all statistics read-only)

**Purpose:** The primary Ethernet/IP monitoring MIB — retrieves frame and byte counts, Ethernet layer statistics (unicast/multicast/broadcast, VLAN, QinQ), IP protocol breakdown, instantaneous and min/max throughput rates, ITU-T Y.1731/RFC 4689 SLA metrics (FTD, FDV, FLR, reordering), BERT results, and layer-2 error statistics (undersized/oversized/jabber/FCS), plus physical link status.

**Key tables / objects:**
- `psnMonEnable` — Starts/stops PSN monitoring.
- `psnMonStatsTable` — Aggregate frame and byte counts per monitoring block.
- `psnMonSizeTable` — Frame count per configurable size bucket (useful for size distribution analysis).
- `psnMonEthStatsTable` — Ethernet frame type breakdown: unicast, multicast, broadcast, VLAN-tagged, QinQ, control, pause.
- `psnMonIpStatsTable` — IP-level counters: IPv4, IPv6, UDP, ICMP frames and bytes; unicast/multicast/broadcast breakdown.
- `psnMonRateStatsTable` — Throughput: `psnMonRateStatsEth` (current fps/bps/%), min, and max rate.
- `psnMonSlaStatsTable` — SLA metrics: `psnMonSlaFtdMin`/`Mean`/`Stdev`/`Range` (frame transfer delay), `psnMonSlaFdv`/`Max`/`Mean` (frame delay variation/jitter), `psnMonSlaReordered`, `psnMonSlaDuplicated`, `psnMonSlaLost`, `psnMonSlaFlr` (frame loss ratio), `psnMonSlaPeu`.
- `psnMonBerStatsTable` — BERT results: `psnMonBerStatsLss`, `psnMonBerStatsTse`, `psnMonBerStatsBer`, `psnMonBerStatsEs`.
- `psnMonErrorStatsTable` — Layer-2 errors: undersized, oversized, jabber, IP header errors, UDP errors, FCS errors — each with rate and seconds.
- `psnLinkStatusTable` — Physical link up/down status per port.

**Typical automation use cases:**
1. Poll `psnMonSlaStatsTable` after a test run to extract FTD mean/stdev, FDV, and FLR for an SLA compliance report.
2. Read `psnMonRateStatsTable` in a loop during an active test to log throughput over time.
3. Check `psnLinkStatusTable.psnLinkStatusValue` as a precondition before starting any test to confirm the Ethernet link is up.

---

### `ATSL-PSN-IMPAIRMENT-MIB.txt`
**Module name:** `ATSL-PSN-IMPAIRMENT-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Injects controlled impairments into a live Ethernet stream — frame loss, delay, bandwidth limitation, frame duplication, and bit error insertion — to emulate WAN impairments and stress-test equipment.

**Key tables / objects:**
- `psnImpLossTable` — Frame loss injection: rate (%), burst size, pattern.
- `psnImpDelayTable` — Artificial delay injection: fixed delay (µs), jitter amplitude, jitter distribution.
- `psnImpBandwidthTable` — Rate limiting: CIR/EIR in Mbps.
- `psnImpDuplicationTable` — Frame duplication rate configuration.
- `psnImpErrorTable` — Bit error injection rate into payload.

**Typical automation use cases:**
1. SET `psnImpDelayTable` to add 50 ms one-way delay and 5 ms jitter to simulate WAN conditions during application performance testing.
2. Configure `psnImpLossTable` to inject 0.1% frame loss and observe `psnMonSlaStatsTable.psnMonSlaFlr` to validate loss measurement accuracy.

---

### `ATSL-PSN-MIRROR-MIB.txt`
**Module name:** `ATSL-PSN-MIRROR-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Controls the PSN capture/mirroring function and retrieves capture statistics — captures Ethernet frames to an internal buffer or file for offline analysis, with counters for captured versus dropped frames.

**Key tables / objects:**
- `psnMirrorCaptureStatsTable` — Capture statistics per stream: captured frame count, dropped frame count, buffer utilization.

**Typical automation use cases:**
1. Start a frame capture, wait for a test event, then poll `psnMirrorCaptureStatsTable` to verify how many frames were captured versus dropped before triggering a file export via `ATSL-PSN-CAPTURE-FILES-MIB`.

---

### `ATSL-PSN-RFC2544-MIB.txt`
**Module name:** `ATSL-PSN-RFC2544-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Automates full RFC 2544 benchmarking (throughput, latency, frame loss, back-to-back, recovery) — configures test objectives, selects frame sizes, triggers execution, and retrieves pass/fail results per sub-test.

**Key tables / objects:**
- `rfc2544Run` — Write to start/stop the RFC 2544 test sequence.
- `rfc2544SettingsTable` — Per-instance objectives: `rfc2544SettingsObjectiveMinThroughput` (%), `rfc2544SettingsObjectiveMaxLatency` (µs), `rfc2544SettingsObjectiveMaxFrameLoss` (%), `rfc2544SettingsObjectiveMinFrameBurst`, `rfc2544SettingsObjectiveMaxRecovery`; `rfc2544SettingsFrameSizes` (bitmask of standard sizes), `rfc2544SettingsUserFrameSizes`.
- `rfc2544StageTable` — Execution state per test stage (queued, running, complete, pass/fail).
- `rfc2544ResultsThroughputTable` — Throughput result per frame size: maximum forwarding rate (fps, Mbps, %).
- `rfc2544ResultsLatencyTable` — Latency result per frame size: min, max, average latency (µs).
- `rfc2544ResultsFrameLossTable` — Frame loss result per frame size and load level.
- `rfc2544ResultsBackToBackTable` — Maximum burst depth result per frame size.
- `rfc2544ResultsRecoveryTable` — Recovery time result per frame size.

**Typical automation use cases:**
1. SET `rfc2544SettingsTable` objectives and frame sizes, write `rfc2544Run` to start, poll `rfc2544StageTable` until all stages are complete, then collect `rfc2544ResultsThroughputTable` and `rfc2544ResultsLatencyTable` for a full RFC 2544 report.
2. Read `rfc2544ResultsFrameLossTable` at multiple load levels to plot a frame loss curve.

---

### `ATSL-FILTER-MIB.txt`
**Module name:** `ATSL-FILTER-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Configures packet capture and analysis filters on Ethernet streams — filters by payload content/mask at a configurable offset, by frame length range, and by bit pattern, with control over which frames are passed or blocked.

**Key tables / objects:**
- `pktFilterControlTable` — Per-stream filter enable/disable and mode (pass/block matching frames).
- `pktFilterTable` — Filter rules: `pktFilterOffsetMode` (from frame start or payload), `pktFilterPayload`, `pktFilterOffset`, `pktFilterOffsetMatchCode`, `pktFilterOffsetMask`, `pktFilterLengthMin`/`Max`, `pktFilterPattern`.
- `pktFilterMacTable` — MAC address-based filter entries.

**Typical automation use cases:**
1. Configure `pktFilterTable` to match a specific IP destination and then read `psnMonStatsTable` to count only the filtered traffic stream.
2. Use `pktFilterMacTable` to isolate traffic from a specific source MAC address before BERT analysis.

---

## 4. Synchronization & Timing

---

### `ATSL-SYNC-MONITOR-MIB.txt`
**Module name:** `ATSL-SYNC-MONITOR-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Controls and retrieves results for wander (MTIE/TDEV), Frequency Phase Perturbation (FPP / time error), and jitter measurements per ITU-T G.8261/G.8262/G.8273 and Telcordia GR-1244 standards.

**Key tables / objects:**
- `syncMonitorRun` — Starts/stops the synchronization monitoring session.
- `syncMonitorWanderSettingsTable` — Wander measurement settings: `syncMonitorWanderSettingsMethod` (MTIE/TDEV), `syncMonitorWanderSettingsLength` (observation window), percentile bounds, bandwidth filter length.
- `syncMonitorWanderAnalysisTable` — MTIE/TDEV results per observation interval.
- `syncMonitorFPPSettingsTable` — FPP/time-error settings: settling time, window length, delta threshold.
- `syncMonitorFPPAnalysisTable` — Time error results: current, min, max phase error values.
- `syncMonitorJitterSettingsTable` — Jitter measurement settings: filter bandwidth, integration time.
- `syncMonitorJitterAnalysisTable` — Jitter results: peak-to-peak, RMS.

**Typical automation use cases:**
1. Configure `syncMonitorWanderSettingsTable` for MTIE analysis and poll `syncMonitorWanderAnalysisTable` to produce a wander profile compliant with ITU-T G.8261.
2. Read `syncMonitorFPPAnalysisTable` to verify time error stays within ±100 ns during a PTP slave lock test.
3. Retrieve `syncMonitorJitterAnalysisTable` peak-to-peak jitter to validate that a recovered clock meets G.742 jitter specifications.

---

### `ATSL-PTP-MIB.txt`
**Module name:** `ATSL-PTP-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Configures and monitors IEEE 1588-2008 (PTP) clocks — supports multiple clock instances, configures transport protocol, PTP profile, addressing mode, and exposes the complete set of IEEE 1588 Data Sets (Default, Current, Parent, Time Properties, Port).

**Key tables / objects:**
- `ptpClockTable` — Per-clock-instance basic info: `ptpClockName`.
- `ptpClockXTable` — Extended PTP config: `ptpClockXTransportProto` (UDP/L2), `ptpClockXProfile` (default, G.8265.1, G.8275.1/2), `ptpClockXAddresingMode` (unicast/multicast).
- `ptpClockDefaultDSTable` — IEEE 1588 Default Data Set: `ptpClockDefaultDSClockIdentity`, `ptpClockDefaultDSQualityClass`/`QualityAccuracy`, `ptpClockDefaultDSPriority1`/`Priority2`, `ptpClockDefaultDSDomainNumber`, `ptpClockDefaultDSSlaveOnly`.
- `ptpClockCurrentDSTable` — IEEE 1588 Current Data Set: offset from master, mean path delay, steps removed.
- `ptpClockParentDSTable` — IEEE 1588 Parent Data Set: grandmaster identity and quality.
- `ptpClockTimePropDSTable` — Time Properties Data Set: TAI offset, PTP timescale, leap-second flags.
- `ptpClockPortDSTable` — Port Data Set: per-port state (initializing/listening/slave/master), log announce/sync intervals.

**Typical automation use cases:**
1. Read `ptpClockCurrentDSTable` offset-from-master and mean-path-delay after a lock period to assess PTP synchronization accuracy.
2. Configure `ptpClockDefaultDSTable` priority1/priority2 and `ptpClockXTable` profile settings for G.8275.1 telecom profile testing.
3. Poll `ptpClockPortDSTable` port state to confirm the device has entered `slave` state before starting time error measurements.

---

### `ATSL-NETTIME-MIB.txt`
**Module name:** `ATSL-NETTIME-MIB`

**Applies to:** Net.Time

**Depends on:** `ATSL-MIB`

**Access:** (structural — defines `atslNetTime` subtree node used by ATSL-NETTIME-EVENTS-MIB)

**Purpose:** Defines the `atslNetTime` OID node (`atslProduct.1`) that serves as the root for all Net.Time device-specific MIBs; no directly accessible objects.

**Key tables / objects:**
- `atslNetTime` — Root OID for all Net.Time sub-MIBs; compile this before `ATSL-NETTIME-EVENTS-MIB`.

**Typical automation use cases:**
1. Import this MIB as a prerequisite before loading `ATSL-NETTIME-EVENTS-MIB` in `MibBuilder`.

---

### `ATSL-NETTIME-EVENTS-MIB.txt`
**Module name:** `ATSL-NETTIME-EVENTS-MIB`

**Applies to:** Net.Time

**Depends on:** `ATSL-MIB`, `ATSL-NETTIME-MIB`

**Access:** Mixed (`netTimeEventEnableTables`/`netTimeEventEnableNotifications` writable; event data read-only)

**Purpose:** Manages Net.Time device events and SNMP notifications — provides a catalogue of all possible events (definitions table), a live list of currently active events (active events table), and SNMP trap/notification objects for event-driven monitoring of NTP/PTP synchronization status changes, GPS lock/unlock, and alarm conditions.

**Key tables / objects:**
- `netTimeEventEnableTables` / `netTimeEventEnableNotifications` — Enable/disable event logging and SNMP trap generation.
- `netTimeEventDefTable` — Event catalogue: `netTimeEventDefID`, `netTimeEventDefName`, `netTimeEventDefSubsystem`, `netTimeEventDefCategory`, `netTimeEventDefDescription`, `netTimeEventDefOriginType`.
- `netTimeEventActiveTable` — Currently active events: `netTimeEventActiveID`, `netTimeEventActiveOrigin`, `netTimeEventActiveTimeStamp`.
- `netTimeEventNotifyID` / `netTimeEventNotifyOrigin` / `netTimeEventNotifyTimeStamp` / `netTimeEventNotifyStatus` — NOTIFICATION-TYPE varbinds sent in SNMP traps.

**Typical automation use cases:**
1. Walk `netTimeEventDefTable` at startup to build a local event name-to-ID mapping for log interpretation.
2. Poll `netTimeEventActiveTable` periodically to check for active GPS-loss or NTP-stratum-change events on Net.Time devices.
3. Configure an SNMP trap receiver and handle `netTimeEventNotifyID` varbinds to trigger automated alerts on synchronization failures.

---

## 5. File & Report Management

---

### `ATSL-FILEMGR-MIB.txt`
**Module name:** `ATSL-FILEMGR-MIB`

**Applies to:** xGenius / Net.Time / both

**Depends on:** `ATSL-MIB`

**Access:** (structural + type definitions only)

**Purpose:** Defines the `fileClasses` OID node and the `FileAction` / `FileOpsResult` textual conventions shared by all file-class MIBs; does not expose any directly accessible data objects — it is a required compilation dependency.

**Key tables / objects:**
- `fileClasses` — Parent OID for all file-class subtrees (`configFiles`, `reportFiles`, `psnCaptFiles`, `logFiles`).
- `FileAction` TC — Enumerates file operations: `idle(0)`, `delete(1)`, `rename(2)`, `import(3)`, `export(4)`, `load(32)`, `save(33)`.
- `FileOpsResult` TC — Enumerates operation outcomes: `idle`, `queued`, `inProgress`, `success`, `fileNotFound`, `deviceNotFound`, `accessDenied`, `readOnly`, `notSupported`, `internalError`, `deviceFull`, `entryExists`, `dirNotEmpty`, `mediaIO`.

**Typical automation use cases:**
1. Must be compiled before any of the four file-class MIBs; include in your `addMibSources()` chain.
2. Use the `FileOpsResult` enumeration in Python to interpret the result code returned by any file operation (`configFilesOpsResult`, `reportFilesOpsResult`, etc.).

---

### `ATSL-CONFIG-FILES-MIB.txt`
**Module name:** `ATSL-CONFIG-FILES-MIB`

**Applies to:** xGenius / Net.Time / both

**Depends on:** `ATSL-MIB`, `ATSL-FILEMGR-MIB`

**Access:** Mixed

**Purpose:** Lists all configuration files stored on the device and provides an operations table to load, save, rename, delete, import, or export them — configuration files store the complete instrument configuration in a proprietary binary format.

**Key tables / objects:**
- `configFilesListTable` — File inventory: `configFilesListName`, `configFilesListDevice`, `configFilesListCreationDate`, `configFilesListSize` (bytes), `configFilesListURL` (HTTP download path relative to device IP).
- `configFilesOpsTable` — Operation interface: create a row, set `configFilesOpsFileName`, `configFilesOpsDevice`, `configFilesOpsArgs` (e.g., new name for rename), `configFilesOpsAction` (FileAction), set `RowStatus=active` to trigger, read `configFilesOpsResult` (FileOpsResult), then destroy the row.

**Typical automation use cases:**
1. Walk `configFilesListTable` to discover available configuration profiles, then SET `configFilesOpsAction=load(32)` to apply a specific configuration before a test.
2. After configuring the instrument, SET `configFilesOpsAction=save(33)` with a new file name to persist the configuration for later recall.
3. Use `configFilesListURL` with the device IP to HTTP-download a config file for backup: `http://{device_ip}/{configFilesListURL}`.

---

### `ATSL-REPORT-FILES-MIB.txt`
**Module name:** `ATSL-REPORT-FILES-MIB`

**Applies to:** xGenius / Net.Time / both

**Depends on:** `ATSL-MIB`, `ATSL-FILEMGR-MIB`

**Access:** Mixed

**Purpose:** Lists test result report files on the device and provides operations to delete, rename, export, or download them via HTTP; report files contain compiled test results in a device-proprietary format.

**Key tables / objects:**
- `reportFilesListTable` — File inventory: name, device, creation date, size, HTTP download URL.
- `reportFilesOpsTable` — Operation interface (same workflow as `configFilesOpsTable`): supports `delete`, `rename`, `export` actions.

**Typical automation use cases:**
1. After a test completes, walk `reportFilesListTable` to find the newest report file and use its `reportFilesListURL` to download it via HTTP for archiving.
2. SET `reportFilesOpsAction=delete` to clean up old report files and free device storage between automated test runs.

> **Distinction vs. ATSL-CONFIG-FILES-MIB:** Report files contain results; they cannot be `load`ed or `save`d. Config files contain settings; they support `load` and `save` in addition to the common file operations.

---

### `ATSL-PSN-CAPTURE-FILES-MIB.txt`
**Module name:** `ATSL-PSN-CAPTURE-FILES-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`, `ATSL-FILEMGR-MIB`

**Access:** Mixed

**Purpose:** Lists Ethernet packet capture files (`.pcap`-compatible) stored on the device and provides operations to delete, rename, or export them; also exposes a post-capture filter table for applying selective packet extraction from a capture file.

**Key tables / objects:**
- `psnCaptFilesListTable` — Capture file inventory: name, device, creation date, size, HTTP download URL.
- `psnCaptFilesOpsTable` — Operations: `delete`, `rename`, `export`.
- `psnCaptPostFilterFilesTable` — Post-capture filter configuration for selectively exporting packets matching specific criteria.

**Typical automation use cases:**
1. After a capture session, walk `psnCaptFilesListTable` and HTTP-GET the PCAP file for analysis in Wireshark or a custom parser.
2. Configure `psnCaptPostFilterFilesTable` to extract only UDP packets matching a specific port before exporting the filtered capture.

---

### `ATSL-LOG-FILES-MIB.txt`
**Module name:** `ATSL-LOG-FILES-MIB`

**Applies to:** xGenius / Net.Time / both

**Depends on:** `ATSL-MIB`, `ATSL-FILEMGR-MIB`

**Access:** Mixed

**Purpose:** Lists device diagnostic log files and provides operations to delete, rename, or export them; log files contain timestamped system event records.

**Key tables / objects:**
- `logFilesListTable` — Log file inventory: `logFilesListName`, `logFilesListDevice`, `logFilesListCreationDate`, `logFilesListSize`, `logFilesListURL`.
- `logFilesOpsTable` — Operations: `delete`, `rename`, `export`.

**Typical automation use cases:**
1. After a firmware upgrade, walk `logFilesListTable` and download the most recent log file to verify the upgrade completed without errors.
2. Periodically export and archive log files from unattended test deployments for post-incident analysis.

---

## 6. Multifunction & Test Control

---

### `ATSL-MULTIFUNCTION-MIB.txt`
**Module name:** `ATSL-MULTIFUNCTION-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed (`mfFuncMode` writable; `mfFuncType`, `mfFuncStatus`, `mfActiveFunc` read-only)

**Purpose:** The **mandatory entry point for controlling multifunction devices** (e.g., xGenius) that can operate in TDM, PSN (Ethernet), or clock-monitor mode but only one mode at a time; provides the function table listing supported modes and the active-function indicator.

> ⚠️ **Critical:** On multifunction devices, **never access function-specific MIB OIDs (TDM, PSN, etc.) before checking `mfActiveFunc`**. Accessing a function's OIDs while a different function is active can cause inconsistent behavior. Always use this MIB to switch modes safely.

**Key tables / objects:**
- `mfFuncTable` — Lists supported functions with `mfFuncType` (`tdm(1)`, `psn(2)`, `clkmon(3)`) and the current `mfFuncMode` per function. `mfFuncMode` semantics depend on function type: for `tdm` it maps to `ATSL-TDM-PORT-MIB::OperationMode`; for `psn` it maps to `ATSL-PSN-GENERATOR-MIB::EndpointMode`; for `clkmon` it is 1 (active) or 0 (external).
- `mfActiveFunc` — Read this scalar first to determine which function is currently active before accessing any function-specific MIB.

**Typical automation use cases:**
1. GET `mfActiveFunc` at session start to determine whether the device is in TDM or PSN mode; if switching is needed, find the appropriate row in `mfFuncTable` and SET `mfFuncMode` to the desired operation mode.
2. Walk `mfFuncTable` to discover all modes supported by a device (e.g., some xGenius units may not support `clkmon`).
3. Before any test: assert `mfActiveFunc == expectedFunction` and raise an error if mismatched, rather than silently operating in the wrong mode.

---

### `ATSL-TEST-MANAGEMENT-MIB.txt`
**Module name:** `ATSL-TEST-MANAGEMENT-MIB`

**Applies to:** xGenius

**Depends on:** `ATSL-MIB`

**Access:** Mixed

**Purpose:** Provides a unified scheduler for starting, stopping, and timing test sessions — supports one-shot immediate start, scheduled future start (via `DateAndTime`), timed duration, and retrieval of actual start/stop times and test progress; also exposes the last power-down timestamp for session auditing.

**Key tables / objects:**
- `testManagementLastPowerDown` — `DateAndTime` of the last power-down event; useful for detecting unexpected reboots.
- `testManagementSchedulerTable` — Per-instance scheduler: `testManagementSchedulerName`, `testManagementSchedulerRun` (write to start/stop), `testManagementSchedulerStartTime` (scheduled `DateAndTime`), `testManagementSchedulerDuration` (seconds), `testManagementSchedulerActualStartTime`/`ActualStopTime` (read-back), `testManagementSchedulerProgress` (0–100%).

**Typical automation use cases:**
1. SET `testManagementSchedulerRun=start` (or write a specific `DateAndTime` to `testManagementSchedulerStartTime`) and poll `testManagementSchedulerProgress` until 100% to know when a timed test has completed.
2. Read `testManagementSchedulerActualStartTime` and `testManagementSchedulerActualStopTime` to record exact test window timestamps in your results database.
3. Check `testManagementLastPowerDown` at session start to detect whether the device rebooted unexpectedly between test runs.

---

## MIB Dependency Tree

The following shows the required compilation order for PySNMP's `MibBuilder`. Indent indicates "must be compiled after parent".

```
SNMPv2-SMI          (standard — always pre-loaded by PySNMP)
SNMPv2-TC           (standard — always pre-loaded by PySNMP)
│
└── ATSL-MIB                          ← compile FIRST; defines root OID and all shared TCs
    │
    ├── ATSL-REGISTRATION-MIB
    ├── ATSL-SYSTEM-MIB
    ├── ATSL-MULTIFUNCTION-MIB
    ├── ATSL-TEST-MANAGEMENT-MIB
    ├── ATSL-SYNC-MONITOR-MIB
    ├── ATSL-PTP-MIB
    ├── ATSL-TDR-MIB
    ├── ATSL-VF-MIB
    │
    ├── ATSL-TDM-MONITOR-MIB          ← TDM monitoring (generic, all interface types)
    │
    ├── ATSL-TDM-PORT-MIB             ← defines FrameType, TimeSlotUse, ABCD, ConnectorType
    │   ├── ATSL-TDM-IMPAIRMENT-MIB
    │   ├── ATSL-E1-PORT-MIB
    │   ├── ATSL-E1-MONITOR-MIB
    │   ├── ATSL-T1-PORT-MIB
    │   ├── ATSL-T1-MONITOR-MIB
    │   ├── ATSL-DATACOM-PORT-MIB
    │   ├── ATSL-DATACOM-MONITOR-MIB
    │   ├── ATSL-C3794-PORT-MIB
    │   └── ATSL-C3794-MONITOR-MIB
    │
    ├── ATSL-PSN-MONITOR-MIB
    ├── ATSL-PSN-GENERATOR-MIB
    ├── ATSL-PSN-PORT-MIB
    ├── ATSL-PSN-IMPAIRMENT-MIB
    ├── ATSL-PSN-MIRROR-MIB
    ├── ATSL-PSN-RFC2544-MIB
    ├── ATSL-FILTER-MIB
    │
    ├── ATSL-FILEMGR-MIB              ← defines fileClasses node + FileAction/FileOpsResult TCs
    │   ├── ATSL-CONFIG-FILES-MIB     ← fileClasses.1
    │   ├── ATSL-REPORT-FILES-MIB     ← fileClasses.2
    │   ├── ATSL-PSN-CAPTURE-FILES-MIB  ← fileClasses.3
    │   └── ATSL-LOG-FILES-MIB        ← fileClasses.4
    │
    └── ATSL-NETTIME-MIB              ← defines atslNetTime node (atslProduct.1)
        └── ATSL-NETTIME-EVENTS-MIB
```

### Minimal subsets for common tasks

| Task | Required MIBs |
|---|---|
| Device identification only | `ATSL-MIB` → `ATSL-REGISTRATION-MIB`, `ATSL-SYSTEM-MIB` |
| E1 BER test | `ATSL-MIB` → `ATSL-TDM-PORT-MIB` → `ATSL-E1-PORT-MIB`, `ATSL-E1-MONITOR-MIB`, `ATSL-TDM-MONITOR-MIB`, `ATSL-TEST-MANAGEMENT-MIB` |
| xGenius multifunction device | Add `ATSL-MULTIFUNCTION-MIB` to any subset above |
| Ethernet SLA test | `ATSL-MIB` → `ATSL-PSN-PORT-MIB`, `ATSL-PSN-GENERATOR-MIB`, `ATSL-PSN-MONITOR-MIB`, `ATSL-TEST-MANAGEMENT-MIB` |
| RFC 2544 | Add `ATSL-PSN-RFC2544-MIB` to the Ethernet SLA subset |
| Config file management | `ATSL-MIB` → `ATSL-FILEMGR-MIB` → `ATSL-CONFIG-FILES-MIB` |
| Net.Time event monitoring | `ATSL-MIB` → `ATSL-NETTIME-MIB` → `ATSL-NETTIME-EVENTS-MIB` |
| PTP / sync analysis | `ATSL-MIB` → `ATSL-PTP-MIB`, `ATSL-SYNC-MONITOR-MIB` |
