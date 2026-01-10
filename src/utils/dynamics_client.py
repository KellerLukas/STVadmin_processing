from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
from hashlib import md5
import shutil
from onepassword import OnePassword

DELAY_MULTIPLIER = 1


class DynamicsClient:
    def __init__(self, working_dir: str = None, debugging_mode: bool = False):
        self._client = None
        if working_dir is None:
            working_dir = os.getcwd()
        self.download_location = os.path.join(
            working_dir, "dynamics_client_temp_folder"
        )
        self.create_temporary_download_folder()
        self.creds = STVAdminCreds()
        self._debugging_mode = debugging_mode

    def __del__(self):
        try:
            shutil.rmtree(self.download_location)
        finally:
            if self._client:
                self.client.quit()

    @property
    def client(self):
        if self._client is None:
            options = webdriver.FirefoxOptions()
            if not self._debugging_mode:
                options.add_argument("--headless")  # Hide browser
            options.set_preference("browser.download.folderList", 2)
            options.set_preference("browser.download.manager.showWhenStarting", False)
            options.set_preference("browser.download.dir", self.download_location)
            options.set_preference(
                "browser.helperApps.neverAsk.saveToDisk", "application/x-gzip"
            )
            self._client = webdriver.Firefox(options=options)
        return self._client

    def download_userlist_to_folder(self, folder):
        self._login()
        self._accept_prompt_if_exists()
        self._initiate_userlist_download()
        return self._wait_for_download_and_move_to_folder(folder, "xlsx")

    def download_riegenlist_to_folder(self, folder):
        self._login()
        self._accept_prompt_if_exists()
        self._initiate_riegenlist_download()
        return self._wait_for_download_and_move_to_folder(folder, "csv")

    def _login(self):
        login_url = "https://nav17.stv-fsg.ch/DynamicsNAV100-NAVUser/WebClient/SignIn.aspx?ReturnUrl=%2fDynamicsNAV100-NAVUser%2fWebClient%2f"
        self.client.get(login_url)
        WebDriverWait(self.client, 10 * DELAY_MULTIPLIER).until(
            EC.presence_of_element_located((By.NAME, "ctl00$PHM$UserName"))
        )
        user = self.client.find_element(By.NAME, "ctl00$PHM$UserName")
        pwd = self.client.find_element(By.NAME, "ctl00$PHM$Password")
        login_button = self.client.find_element(By.NAME, "ctl00$PHM$LoginButton")
        user.send_keys(self.creds.client_id)
        pwd.send_keys(self.creds.client_secret)
        login_button.click()

    def _accept_prompt_if_exists(self):
        try:
            WebDriverWait(self.client, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//button[@title='Ja']"))
            ).click()
        except:
            pass

    def _click_element_when_ready(self, xpath, index=None):
        """Helper function to wait for an element to be clickable and then click it.

        Args:
            xpath (str): The XPath of the element to click.
            index (int, optional): The index of the item to select from the list, if it is a list.
            wait_time (int, optional): The wait time for the element to become clickable. Default is 10 seconds.
        """
        wait_time = 10 * DELAY_MULTIPLIER
        self._wait_for_javascript_completion(timeout=wait_time)
        self._wait_for_dom_stability(timeout=wait_time)
        # Wait for elements matching the XPath to be present
        WebDriverWait(self.client, wait_time).until(
            lambda driver: len(self.client.find_elements(By.XPATH, xpath)) > 0
        )
        time.sleep(0.3)  # Small delay to ensure stability
        # Get all matching elements
        elements = self.client.find_elements(By.XPATH, xpath)

        # Select the desired element by index, or the first element if index is None
        element_to_click = elements[index] if index is not None else elements[0]

        # Ensure the element is visible before clicking
        WebDriverWait(self.client, wait_time).until(EC.visibility_of(element_to_click))

        element_to_click.click()

    def _wait_for_dom_stability(self, timeout=10, poll_frequency=0.1):
        """
        Wait until the DOM stabilizes by monitoring its state.
        Returns True if stabilized within timeout, raises an exception otherwise.
        """

        def get_dom_hash():
            """Generate a lightweight hash of the DOM content."""
            return md5(
                self.client.execute_script("return document.body.innerHTML").encode(
                    "utf-8"
                )
            ).hexdigest()

        previous_hash = None
        stable_count = 0
        max_stable_checks = (
            3  # Number of consecutive stable checks to confirm stability
        )

        for _ in range(int(timeout / poll_frequency)):
            current_hash = get_dom_hash()
            if current_hash == previous_hash:
                stable_count += 1
                if stable_count >= max_stable_checks:
                    return True  # DOM stabilized
            else:
                stable_count = 0  # Reset counter if DOM changes
            previous_hash = current_hash
            time.sleep(poll_frequency)

        raise Exception("DOM did not stabilize within the given timeout.")

    def _wait_for_javascript_completion(self, timeout=10 * DELAY_MULTIPLIER):
        """Wait for all JavaScript events to complete."""
        WebDriverWait(self.client, timeout).until(
            lambda driver: self.client.execute_script("return document.readyState")
            == "complete"
        )

    def _initiate_userlist_download(self):
        # Using the helper function with list selection where needed
        self._click_element_when_ready(
            "//li[contains(@class, 'ms-cui-tt')]/a[contains(@title, 'Bericht')]"
        )
        self._click_element_when_ready(
            "//span[@class='ms-cui-ctl-largelabel' and text()='Mitgliederverwaltung']/ancestor::a[@class='ms-cui-ctl-large']"
        )
        self._click_element_when_ready(
            "//span[@class='ms-cui-ctl-largelabel' and text()='Exportieren']/ancestor::a[@class='ms-cui-ctl-large']"
        )
        self._click_element_when_ready(
            "//span[@class='ms-cui-tt-span' and text()='Aktionen']/ancestor::a[@class='ms-cui-tt-a']/ancestor::li[@class='ms-cui-tt ']",
            index=1,
        )
        self._click_element_when_ready(
            "//a[@class='ms-cui-ctl-large' and .//span[@class='ms-cui-ctl-largelabel' and contains(normalize-space(), 'Alle') and contains(normalize-space(), 'auswählen')]]",
            index=0,
        )
        self._click_element_when_ready(
            "//span[@class='ms-cui-tt-span' and text()='Start']/ancestor::a[@class='ms-cui-tt-a']/ancestor::li[@class='ms-cui-tt ']",
            index=0,
        )
        self._click_element_when_ready(
            "//span[@class='ms-cui-ctl-largelabel' and text()='Exportieren']/ancestor::a[@class='ms-cui-ctl-large']",
            index=1,
        )

    def _initiate_riegenlist_download(self):
        # Using the helper function with list selection where needed
        self._click_element_when_ready(
            "//li[contains(@class, 'ms-cui-tt')]/a[contains(@title, 'Bericht')]"
        )
        self._click_element_when_ready(
            "//span[@class='ms-cui-ctl-largelabel' and text()='Organverwaltung']/ancestor::a[@class='ms-cui-ctl-large']"
        )
        self._click_element_when_ready(
            "//span[@class='ms-cui-ctl-largelabel' and contains(normalize-space(), 'Organ') and contains(normalize-space(), 'Export')]/ancestor::a[@class='ms-cui-ctl-large']",
            index=0,
        )

    def _wait_for_download_and_move_to_folder(self, folder, filetype):
        while not self.temp_folder_contains_filetype(filetype):
            time.sleep(0.5)  # Wait for the file to appear
        time.sleep(0.5)
        return self.move_file_with_type_to_folder(filetype, folder)

    def create_temporary_download_folder(self):
        if os.path.isdir(self.download_location):
            shutil.rmtree(self.download_location)
        os.mkdir(self.download_location)

    def temp_folder_contains_filetype(self, filetype: str):
        return any(
            file.endswith(filetype) for file in os.listdir(self.download_location)
        )

    def move_excel_to_folder(self, folder):
        return self.move_file_with_type_to_folder("xlsx", folder)

    def move_csv_to_folder(self, folder):
        return self.move_file_with_type_to_folder("csv", folder)

    def move_file_with_type_to_folder(self, filetype, folder):
        files = [
            file for file in os.listdir(self.download_location) if filetype in file
        ]
        if len(files) != 1:
            raise ValueError(f"Expected one {filetype} file, but found: {files}")
        filename = files[0]
        os.rename(
            os.path.join(self.download_location, filename),
            os.path.join(folder, filename),
        )
        return filename


class STVAdminCreds:
    def __init__(self):
        self._client_id = None
        self._client_secret = None
        self.op = OnePassword()
        self.item_uuid = "utpuxkadynh4bnoqufqp5umzvy"

    @property
    def client_id(self):
        if self._client_id is None:
            self._client_id = self.get_client_id()
        return self._client_id

    @property
    def client_secret(self):
        if self._client_secret is None:
            self._client_secret = self.get_client_secret()
        return self._client_secret

    def get_client_id(self):
        return self.get_field("username")

    def get_client_secret(self):
        return self.get_field("password")

    def get_field(self, label):
        item = self.op.get_item(uuid=self.item_uuid)
        fields = item["fields"]
        for field in fields:
            if field["id"] == label:
                return field["value"]
