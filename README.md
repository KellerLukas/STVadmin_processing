# STVAdmin Processing
**A tool that makes life easier when trying to work with the very limited and old [STV Admin Database](https://www.stv-fsg.ch/de/mitglied-verein/stv-admin.html) (Microsoft Dynamics)**

Note: This tool is made specifically to work with the setup of one particular sports club. It handles some very strange workarounds that were put in place many years ago to make their setup of various groups and categories work with the limitations of the STV Admin Database. Hence many translations & special cases had to me made which probably makes this unusable for any other sports club, sorry :wink:

### Functionality:
- Simple streamlit UI to interact with the tool
- Automatic retrieval of an up-to-date database snapshot from the STV Admin Database using Selenium webdriver (I do not have access to any APIs!) resulting in two csv files containing personal data as well as group membership information.
- Convert the exported csv into a class based database.
- Export a special csv file used to import the recipients into some newsletter tool (where duplicate email addresses are combined in a specific way)
- Export lists containing members of each group (a very tedious task in the original database)
- Export special lists and statistics used for various tasks throughout the year.

### Note
The custom database used is far from optimal, but it was fun implementing. As the size of the database is limited naturally by the local population, there is no real reason to improve performance with a proper database (e.g. SQL or even keeping everything as a simple dataframe).

For privacy reasons two directories are not commited to this repositoriy:

- demo folder: containing jupyter notebooks and other files used to manually extract statistics and other information not used regularly
- config folder: containing local paths used