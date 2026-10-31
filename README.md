# STVAdmin Processing

A Streamlit app for managing membership data for one sports club. It retrieves
members, institutes (Riegen), and functions from mySTV, prepares club-specific
exports, and can synchronize newsletter data with CleverReach.

The app includes club-specific mappings and rules, so it is not intended to
work for other clubs without modification.

## Features

- Retrieve and process mySTV data and view membership statistics.
- Export institute lists, coach lists, an Infoheft address list (grouped by
  household), no-mail lists, and annual general meeting (GV) lists.
- Export CleverReach data as CSV or synchronize members directly with CleverReach.
- Save timestamped mySTV snapshots and compare them with current data.
- Compare mySTV with Fairgate, showing field differences and members missing from
  either source. Manual Fairgate Excel exports are also supported in scripts and notebooks.
- Check the mySTV refresh status, trigger a server refresh, and clear local caches.

## Requirements and setup

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/)
- Access to the club's mySTV, Fairgate, and CleverReach integrations and their
  configured 1Password items

Provide the deployment-specific files `src/config/constants.py`,
`src/config/paths.py`, and `src/config/fairgate_export.json`. They contain club
and integration identifiers, storage paths, export filenames, and Fairgate
export settings. These files are intentionally excluded from Git; use the club's
existing configuration.

Install dependencies and start the app from the repository root:

```bash
uv sync
uv run streamlit run home.py
```

Exports are written to `OUTPUT_FOLDER` under `WORKING_DIR_PATH`; snapshots use
`MYSTV_SNAPSHOT_FOLDER` under the same directory. These paths are configured in
`src/config/paths.py`. The clients require no browser automation. The
**Open output folder in Finder** button currently requires macOS.

## Usage

The app checks the mySTV refresh status at startup. Click the status pill to check
again. **Datenbank neu laden** starts a server refresh; **Reset cache** clears
local data so the next access downloads it again. A server refresh does not block
exports or comparisons, and its completion does not automatically clear local data.

In **Snapshot Vergleich**, create a snapshot or select one by timestamp to compare
with the current state. **Fairgate Vergleich** downloads an online Fairgate export.
Snapshot creation and comparisons reload their source data without triggering a
server refresh.

## Privacy

Member data, exports, and snapshots contain personal information. Keep them in
the club's approved storage and do not commit them. The `demo` directory and
`src/config` files are excluded from version control. Only load trusted snapshot
files: they use Python's pickle format.
