# STVAdmin Processing

A Streamlit app for managing membership data for one sports club. It retrieves
member and group information from mySTV, prepares club-specific exports, and
can synchronize newsletter data with CleverReach.

The app includes club-specific mappings and rules, so it is not intended to
work for other clubs without modification. But the base client classes should contain no club-specific content.

## Features

- Retrieve and process member and group data from mySTV.
- View membership statistics.
- Export institute (Riegen) lists, coach lists, an Infoheft address list (grouped by Household),
  no-mail lists, and annual general meeting (GV) lists.
- Export CleverReach data as CSV or synchronize members directly with
  CleverReach.

## Requirements and setup

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/)
- Access to the club's mySTV account and the configured 1Password items for
  mySTV and CleverReach

Before starting the app, provide the deployment-specific configuration modules
`src/config/constants.py` and `src/config/paths.py`. They are intentionally
ignored by Git and are not included in this repository. They contain club and
integration identifiers, local/shared-folder paths, and export filenames; use
the club's secure configuration rather than committing these values.

Install the Python dependencies:

```bash
uv sync
```

Start the app with:

```bash
uv run streamlit run home.py
```

The app retrieves data from mySTV when an export or statistics action is
selected. Generated files are written to the configured working directory's
`OUT` folder.


## Privacy

Member data and generated exports contain personal information. Keep them in
the club's approved storage and do not commit them. The `demo` directory and
the deployment-specific files in `src/config` are excluded from version
control.

## Fairgate

`FairgateClient` uses the normal website login and Excel-export endpoints with
`requests.Session`. It does not require a browser or the paid REST API. It uses
`CredentialsBase`, with the same 1Password field IDs as mySTV: `username` and
`credential`. No credentials or session cookies are stored in the export configuration.

Configure the following in the existing, Git-ignored configuration modules:

- `src/config/constants.py`: `FAIRGATE_CLUB_SLUG` (the URL identifier between the
  hostname and `/backend`) and `OP_FAIRGATE_ITEM_UUID`.
- `src/config/paths.py`: `FAIRGATE_EXPORT_CONFIG_PATH`, a `pathlib.Path` pointing to
  `src/config/fairgate_export.json` independently of the working directory.
- `src/config/fairgate_export.json`: `club_slug`, `columnType`, `columnNames`, and
  `extraSearch`. The column metadata comes from the successful export request's
  decoded `formhidden` field. Keep the complete column definitions and headings
  needed by `FairgateProcessor`. Do not copy credentials, cookies, or member rows.

The client generates both `selctCol` and `formhidden` from this single configuration,
with no selected-contact or search filters. The metadata is a configured snapshot;
update it if the club's export fields change. It is not read from browser storage.
The local configuration has been populated from the supplied capture and is ignored
by Git, like the other deployment-specific settings.

```python
from src.fairgate.fairgate_processor import FairgateProcessor

fg = FairgateProcessor()  # Defaults to FAIRGATE_CLUB_SLUG; no I/O yet.
# Or: fg = FairgateProcessor(club_slug="your-club-url-identifier")
# Or: fg = FairgateProcessor(filename="manual-export.xlsx")
# Or: fg = FairgateProcessor.from_excel("manual-export.xlsx")

members = fg.members  # Loads fg_data once, then filters and indexes the members.
former_members = fg.former_members  # Uses the same source snapshot.
fg.clear_cached_data()  # The next access reloads the selected source.
```

Choose either `filename` or `club_slug`, not both. A supplied file object must
remain open until loading/reloading completes. Paths and file objects go through
the same Excel reader as online downloads, preserving identifiers as strings.
Online loading closes the HTTP session immediately after the download; the
processor retains only the data. No notebook thread wrapper is needed.

For the original Excel bytes without processing:

```python
from src.config.constants import FAIRGATE_CLUB_SLUG
from src.fairgate.fairgate_client import FairgateClient

with FairgateClient(club_slug=FAIRGATE_CLUB_SLUG) as fg_client:
    fg_client.login()
    excel_bytes = fg_client.export_contacts()
```

Requests have timeouts and do not follow redirects automatically. Expired sessions
raise `FairgateAuthenticationError`; call `login()` again explicitly. Requests and
credential submissions are not retried automatically. Logs omit credentials,
tokens, response bodies, and member data.

## Snapshots and comparisons

The Streamlit **Snapshot Vergleich** section sits above **Fairgate Vergleich**.
Use **Snapshot erstellen** to capture and save the current data. Saved snapshots
are listed newest first by their timestamp in the Europe/Zurich timezone; a newly
saved snapshot is selected automatically. Select a snapshot and choose
**Mit aktuellem Stand vergleichen** to load fresh current data and compare it.
The result uses the same statistics, missing-member tables, and Unicode detail
view as the Fairgate comparison. **Liste aktualisieren** rereads local storage;
there is no periodic catalog or server-status polling. A running server refresh
does not disable these actions; only another local background task does.

MySTV snapshots contain processed members and their institutes and functions.
Capture always clears the local MySTV member/institute caches and downloads both
datasets again. It does **not** trigger the server's database refresh. Cross-system
comparison also clears the Fairgate cache before downloading its data.

Configure `MYSTV_SNAPSHOT_FOLDER` in `src/config/paths.py`; it is resolved under
`WORKING_DIR_PATH`. Each snapshot is a single `.pkl` file. Pickle preserves indexes,
leading zeros, dates, missing values, nested values, and pandas data types without
a new dependency. Only load trusted files created by this application: unpickling
untrusted files can execute code. Snapshots are private data and must not be committed.

```python
from src.orchestrator import Orchestrator

orch = Orchestrator()
saved = orch.take_and_dump_snapshot()  # Downloads fresh data and returns metadata.
snapshots = orch.list_snapshots()  # Newest first; metadata has uuid and UTC date.
result = orch.compare_to_snapshot(saved.uuid)  # Downloads current data again.
result.differences
result.missing_in_left  # In the saved snapshot, absent from current data.
result.missing_in_right  # In current data, absent from the saved snapshot.
```

`compare_to_fairgate_export()` returns the same `ComparisonResult`; left is MySTV
and right is Fairgate. The Streamlit view uses the named result fields rather than
a positional tuple. Differences keep the original values for Unicode inspection.

For comparisons entirely from already-loaded data, use
`compare_db_snapshots(left, right)`. It does not download anything. MySTV inputs
must be `MySTVSnapshot` instances so institutes and functions are included. A Fairgate
input is a `DBSnapshot(type=DBSnapshotType.FAIRGATE, members=fg.members)`;
persistent Fairgate snapshots are not implemented yet. Models live in
`src.comparison.comparison_models` and the comparator in `src.comparison.compare_dbs`.

Snapshot capture/loading/listing lives on `MySTVSnapshot` (`from_processor`,
`load`, `list_snapshots`); the former `MySTVSnapshots` wrapper is removed.
Serialization automatically includes dataclass constructor fields. New fields with
defaults can be omitted from older snapshots. Adding required fields or renaming
fields/classes may require migration; pandas upgrades can also affect pickle
compatibility. The unfinished CSV/JSON snapshot format is not loaded automatically.

Same-system comparisons ignore MySTV's derived fields (enum names prefixed `_`)
and the opaque `memberships`, `honors`, and `squads` fields. Fairgate's age, birth
year, and both membership-year counters are ignored. Other scalars, lists, tuples,
and dictionaries are compared structurally; missing scalar values and empty strings
are treated alike. Ignored fields remain stored in snapshots. Fields absent from
both snapshots are skipped; a comparable field absent on only one side raises a
schema-mismatch error instead of silently disappearing.

MySTV historical comparisons check complete institute/function pairs. Fairgate
comparison only checks the youth functions represented by its website field; it
does not treat other MySTV groups as missing. Category and gender mapping remains
enabled for cross-system comparisons. Comparison policy is defined in
`src/comparison/comparison_config.py`.

Storage deliberately remains simple: direct writes, no automatic migrations,
atomic publication, or club/schema-version validation. These are deferred; retain
backups of reference snapshots. Loading a snapshot never logs in or recomputes
historical derived fields.
