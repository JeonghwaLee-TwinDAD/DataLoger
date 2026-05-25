
All projects
Data Logger
Universal Data Logger



How can I help you today?



Start a task in Cowork
Logger refactoring
Last message 15 minutes ago
Memory
Only you
Project memory will show here after a few chats.

Instructions
Add instructions to tailor Claude’s responses

Files
1% of project capacity used

DataLogger_Requirements.docx
194 lines

docx



High_Speed_Logger.py
442 lines

py


DataLogger_Requirements.docx
13.58 KB •194 lines
•
Formatting may be inconsistent from source

**F18 Blowdown Chamber — Data Logger Requirements**	CONFIDENTIAL

**DATA LOGGER REQUIREMENTS**

F18 Blowdown Chamber  |  High-Speed Acquisition System

Document number: **DL-REQ-001**

Revision: 1.0

Status: Draft

Source file: logger.py  (f18_blowdown package)

Prepared by: Test Systems Group

# **1. Purpose and Scope**

This document specifies functional, performance, and interface requirements for the **DataLogger** component of the F18 Blowdown Chamber data acquisition system. Requirements are derived directly from the implementation in logger.py and govern behaviour that must be preserved across any future refactoring, porting, or test-stand integration.

All requirements use RFC 2119 keyword conventions: **SHALL** denotes a mandatory requirement, **SHOULD** denotes a recommended but non-mandatory behaviour, and **MAY** denotes an optional capability.

| **Scope boundary** In scope: data serialisation, file naming, threading model, error handling, and the public API of DataLogger. Out of scope: hardware acquisition (DataProducer), plot rendering (BlowdownDashboard), and hydraulic calculations (processing.py). |
| --- |

# **2. Definitions**

| **Term** | **Definition** |
| --- | --- |
| **DataLogger** | The class defined in logger.py responsible for serialising recorded Series data to CSV on disk. |
| **Series** | A typed data container (models.py) holding two parallel lists of floats — xs (x-axis values) and ys (y-axis values) — along with a name identifier. |
| **Snapshot** | A deep copy of a Series produced by Series.snapshot(). Snapshots are taken on the calling thread and passed to background threads to eliminate shared-state races. |
| **SID_TIME** | Series identifier 'Time'. Carries elapsed time (s) as both x and y. |
| **SID_FLOW** | Series identifier 'Flow'. Carries differential pressure (PSI) as x and computed flow rate (GPM) as y. |
| **Recording run** | The contiguous block of samples captured between a Start Record and Stop Record user action. |
| **Daemon thread** | A Python thread marked daemon=True that is killed automatically when the main process exits, without blocking shutdown. |
| **DXA** | Device-independent measurement unit used in .docx layout. 1440 DXA = 1 inch. |

# **3. Functional Requirements**

## **3.1  Data Ingestion**

DataLogger SHALL accept recorded data exclusively through the save() and save_async() public methods. No direct attribute access to internal Series data is permitted from outside the class.

| **ID** | **Requirement** | **Priority** | **Source** |
| --- | --- | --- | --- |
| DL-F-001 | DataLogger SHALL accept a time Series and a flow Series as inputs to both save() and save_async(). Either argument MAY be None. | **SHALL** | *logger.py:save()* |
| DL-F-002 | DataLogger SHALL extract the time column from time_series.xs when time_series is not None and time_series.xs is non-empty. | **SHALL** | *logger.py:save()* |
| DL-F-003 | DataLogger SHALL extract the delta-pressure column from flow_series.xs and the flow column from flow_series.ys when flow_series is not None and flow_series.xs is non-empty. | **SHALL** | *logger.py:save()* |
| DL-F-004 | DataLogger SHALL write no output file and SHALL return None when all input Series are either None or contain empty xs lists. | **SHALL** | *logger.py:save()* |
| DL-F-005 | DataLogger SHALL emit a console message '[DataLogger] No data to export.' whenever save() exits due to empty inputs. | **SHOULD** | *logger.py:save()* |

## **3.2  Output File**

Saved files SHALL be valid UTF-8 CSV readable by pandas read_csv() without additional arguments.

| **ID** | **Requirement** | **Priority** | **Source** |
| --- | --- | --- | --- |
| DL-F-010 | The output file SHALL be a comma-separated values (CSV) file with a header row as the first line. | **SHALL** | *logger.py:save()* |
| DL-F-011 | The CSV header SHALL contain the column names: 'time', 'delp', 'flow' in that order when all three Series are present. | **SHALL** | *logger.py:save()* |
| DL-F-012 | Columns that have no corresponding Series data SHALL be omitted from the header and all data rows. | **SHALL** | *logger.py:save()* |
| DL-F-013 | The output file SHALL NOT include a pandas row-index column (i.e. index=False). | **SHALL** | *logger.py:save()* |
| DL-F-014 | Each data row SHALL contain exactly one sample, with columns aligned to the header. | **SHALL** | *logger.py:save()* |

## **3.3  File Naming and Storage Path**

| **ID** | **Requirement** | **Priority** | **Source** |
| --- | --- | --- | --- |
| DL-F-020 | The output filename SHALL follow the pattern: {part_number}_{serial_number}_{timestamp}.csv | **SHALL** | *logger.py:save()* |
| DL-F-021 | The timestamp component SHALL be formatted as YYYYmmdd_HHMMSS (strftime '%Y%m%d_%H%M%S'), representing local system time at the moment save() is called. | **SHALL** | *logger.py:save()* |
| DL-F-022 | The output file SHALL be written to the directory specified by DataLogger.datalog_path. | **SHALL** | *logger.py:__init__()* |
| DL-F-023 | DataLogger SHALL create the full directory tree for datalog_path if it does not already exist (os.makedirs with exist_ok=True). | **SHALL** | *logger.py:save()* |
| DL-F-024 | DataLogger SHALL default to the value of config.DATALOG_PATH when no datalog_path argument is supplied to __init__(). | **SHALL** | *logger.py:__init__()* |
| DL-F-025 | DataLogger SHALL emit a console message '[DataLogger] Saved → {filepath}' on successful write, where {filepath} is the absolute path of the created file. | **SHOULD** | *logger.py:save()* |
| DL-F-026 | DataLogger SHALL return the absolute path of the written file as a str from save() on success. | **SHALL** | *logger.py:save()* |

## **3.4  Threading and Concurrency**

File I/O is intentionally off-loaded to a background thread so that the Matplotlib event loop is not blocked during save operations. This section captures all threading requirements.

| **ID** | **Requirement** | **Priority** | **Source** |
| --- | --- | --- | --- |
| DL-F-030 | save_async() SHALL snapshot all Series arguments on the calling thread before spawning any background thread. | **SHALL** | *logger.py:save_async()* |
| DL-F-031 | save_async() SHALL pass the snapshot copies — not references to the originals — to the background thread. | **SHALL** | *logger.py:save_async()* |
| DL-F-032 | The background thread spawned by save_async() SHALL be marked daemon=True so that it does not block process shutdown. | **SHALL** | *logger.py:save_async()* |
| DL-F-033 | save_async() SHALL return to the caller immediately after thread.start() without waiting for the I/O to complete. | **SHALL** | *logger.py:save_async()* |
| DL-F-034 | save() SHALL be safe to call directly on any thread; it SHALL NOT acquire or release any lock. | **SHALL** | *logger.py:save()* |
| DL-F-035 | DataLogger itself SHALL hold no mutable shared state between calls. It SHALL be stateless beyond datalog_path. | **SHALL** | *logger.py* |

# **4. Performance Requirements**

## **4.1  Acquisition Impact**

Because DataLogger runs exclusively on background threads, it SHALL impose zero latency on the hardware polling loop during save operations.

| **ID** | **Requirement** | **Priority** | **Source** |
| --- | --- | --- | --- |
| DL-P-001 | The time between the user triggering Stop Record and save_async() returning to the UI thread SHALL be less than 5 ms under all conditions. | **SHALL** | *logger.py:save_async()* |
| DL-P-002 | DataLogger SHALL not block the Matplotlib animation callback (running at 50 ms intervals) at any point during a save operation. | **SHALL** | *Design constraint* |
| DL-P-003 | Memory allocated for the snapshot inside save_async() SHALL be released when the background thread completes. | **SHOULD** | *logger.py:_save()* |

## **4.2  Sample Volume**

The producer targets ~800 Hz. A typical test run lasting 30 seconds therefore produces approximately 24,000 samples per series.

| **ID** | **Requirement** | **Priority** | **Source** |
| --- | --- | --- | --- |
| DL-P-010 | DataLogger SHALL correctly serialise recordings of at least 100,000 samples per Series without data loss or truncation. | **SHALL** | *Derived from 800 Hz × 120 s* |
| DL-P-011 | DataLogger SHOULD complete the CSV write for a 30-second recording (approx. 24,000 rows) within 2 seconds on the target hardware. | **SHOULD** | *Operational target* |

# **5. Interface Requirements**

## **5.1  Public API**

The following table defines the complete public interface of DataLogger. No other methods or attributes may be accessed by external callers.

| **Method / Attribute** | **Signature** | **Description** |
| --- | --- | --- |
| __init__() | datalog_path: str = DATALOG_PATH | Construct DataLogger. Stores path; creates no files. |
| save() | time_series, flow_series, part_number, serial_number -> Optional[str] | Blocking save. Returns path or None. |
| save_async() | time_series, flow_series, part_number, serial_number -> None | Non-blocking save on a daemon thread. |
| datalog_path | str | Read-write attribute. Output directory. |

## **5.2  Input Types**

| **ID** | **Requirement** | **Priority** | **Source** |
| --- | --- | --- | --- |
| DL-I-001 | part_number and serial_number SHALL be str. DataLogger SHALL not validate their format or content. | **SHALL** | *logger.py:save()* |
| DL-I-002 | time_series and flow_series SHALL be instances of models.Series or None. No other type is accepted. | **SHALL** | *logger.py:save()* |
| DL-I-003 | DataLogger SHALL read only the xs and ys attributes of a Series. It SHALL NOT call any Series method that mutates state. | **SHALL** | *logger.py:save()* |

## **5.3  Output Types**

| **ID** | **Requirement** | **Priority** | **Source** |
| --- | --- | --- | --- |
| DL-O-001 | save() SHALL return str (the absolute file path) on success, and None when no data is available to write. | **SHALL** | *logger.py:save()* |
| DL-O-002 | save_async() SHALL always return None. The file path is not surfaced to the caller. | **SHALL** | *logger.py:save_async()* |
| DL-O-003 | DataLogger SHALL NOT raise an exception on empty-data input. It SHALL return None and log a console message. | **SHALL** | *logger.py:save()* |

# **6. Error Handling**

| **ID** | **Requirement** | **Priority** | **Source** |
| --- | --- | --- | --- |
| DL-E-001 | If os.makedirs() raises an OSError, DataLogger SHALL propagate the exception to the caller (or background thread). It SHALL NOT silently discard I/O errors. | **SHALL** | *logger.py:save()* |
| DL-E-002 | If pd.DataFrame.to_csv() raises an exception, DataLogger SHALL propagate the exception. It SHALL NOT write a partial file and return a path. | **SHALL** | *logger.py:save()* |
| DL-E-003 | Exceptions raised on the background thread in save_async() SHALL be printed to stderr or logged. They SHALL NOT crash the main process. | **SHOULD** | *logger.py:_save()* |
| DL-E-004 | DataLogger SHALL NOT catch KeyboardInterrupt or SystemExit. | **SHALL** | *Python best practice* |

# **7. Configuration**

All tuneable values affecting DataLogger are defined in config.py. DataLogger SHALL read these values only at construction time; runtime changes to config.py constants SHALL NOT affect an already-instantiated DataLogger.

| **Term** | **Definition** |
| --- | --- |
| **DATALOG_PATH** | Default directory for CSV output. Overridable via the datalog_path constructor argument. Default: C:\_Data_Log\ |
| **PART_NUMBER** | Default part number injected by the TPI orchestrator when calling save_async(). DataLogger itself does not consume this constant. |

# **8. Dependencies**

| **ID** | **Requirement** | **Priority** | **Source** |
| --- | --- | --- | --- |
| DL-D-001 | DataLogger SHALL depend on the pandas library for DataFrame construction and CSV serialisation. | **SHALL** | *logger.py imports* |
| DL-D-002 | DataLogger SHALL depend on the Python standard library modules: os, threading, time. | **SHALL** | *logger.py imports* |
| DL-D-003 | DataLogger SHALL depend on models.Series for type-checked input arguments. | **SHALL** | *logger.py imports* |
| DL-D-004 | DataLogger SHALL NOT depend on matplotlib, tkinter, or any GUI framework. | **SHALL** | *Separation of concerns* |
| DL-D-005 | DataLogger SHALL NOT import from acquisition.py or processing.py. | **SHALL** | *Separation of concerns* |

# **9. Requirement Traceability**

The table below maps each requirement to its corresponding location in logger.py and the test case that verifies it.

| **ID** | **Requirement (summary)** | **Source location** | **Test case** |
| --- | --- | --- | --- |
| DL-F-001 | Accept time + flow Series (either may be None) | save() sig | test_save_none_inputs |
| DL-F-004 | Return None and no file on empty data | save() guard | test_save_empty_series |
| DL-F-010-014 | Valid CSV with correct columns / no index | save() body | test_csv_schema |
| DL-F-020-021 | Filename pattern with timestamp | save() body | test_filename_format |
| DL-F-023 | Create directory tree if missing | makedirs() | test_creates_directory |
| DL-F-030-031 | Snapshot before thread spawn | save_async() | test_snapshot_isolation |
| DL-F-032 | Background thread is daemon | save_async() | test_thread_daemon_flag |
| DL-F-035 | No mutable shared state | class design | test_concurrent_saves |
| DL-P-001 | save_async() returns in less than 5 ms | save_async() | test_async_return_latency |
| DL-P-010 | Handles 100,000 samples without loss | save() | test_large_dataset |
| DL-E-001-002 | Propagate I/O exceptions | save() | test_io_error_propagation |

# **10. Revision History**

| **Rev** | **Date** | **Author** | **Description** |
| --- | --- | --- | --- |
| 1.0 | 2026-05-24 | Test Systems Group | Initial release. Requirements derived from logger.py (f18_blowdown refactor). |

*— End of document —*

		Test Systems Group	Page 	*DL-REQ-001  Rev 1.0*