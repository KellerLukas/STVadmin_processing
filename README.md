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

Install the Python dependencies and Chromium:

```bash
uv sync
uv run playwright install chromium
```

Start the app with:

```bash
uv run streamlit run home.py
```

The app retrieves data from mySTV when an export or statistics action is
selected. Generated files are written to the configured working directory's
`OUT` folder.

## Experimental MySTV HTTP client

`MySTVClientV2` is available separately from the application's existing client
while its HTTP-only authentication flow is reviewed. It is not yet used by the
Streamlit app and has not been runtime-verified against mySTV. Use it only when
you are ready to make live requests:

```python
from src.mySTV.mystv_client_v2 import MySTVClientV2
from src.config.constants import MYSTV_CLUB_ID

with MySTVClientV2(club_id=MYSTV_CLUB_ID) as client:
    client.login()
    members = client.get_members_stream_raw()
```

The client requires an interactive 1Password credential item and supports the
observed password-based authorization-code flow; additional login challenges
such as MFA are not handled automatically.

## Privacy

Member data and generated exports contain personal information. Keep them in
the club's approved storage and do not commit them. The `demo` directory and
the deployment-specific files in `src/config` are excluded from version
control.
