from selenium import webdriver
from selenium.webdriver.common.by import By
import time
from selenium.webdriver.firefox.options import Options
import os
import shutil
from onepassword import OnePassword





class DynamicsClient:
    def __init__(self, working_dir: str = None):
        self._client = None
        if working_dir is None:
            working_dir = os.getcwd()
        self.download_location = os.path.join(working_dir, "dynamics_client_temp_folder")
        self.create_temporary_download_folder()
        self.creds = STVAdminCreds()
        
    def __del__(self):
        shutil.rmtree(self.download_location)
        self.client.quit()
            

    @property
    def client(self):
        if self._client is None:        
            options = Options()
            options.set_preference("browser.download.folderList", 2)
            options.set_preference("browser.download.manager.showWhenStarting", False)
            options.set_preference("browser.download.dir", self.download_location)
            options.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/x-gzip")
            self._client = webdriver.Firefox(options=options)
        return self._client
    
    def download_list_to_folder(self,folder):
        self._login()
        time.sleep(1)
        self._initiate_download()
        while not self.temp_folder_contains_xlsx():
            pass
        return self.move_file_to_folder(folder)
        

    def _login(self):
        login_user_name = "ctl00$PHM$UserName"
        login_pwd_name = "ctl00$PHM$Password"
        login_submit_name = "ctl00$PHM$LoginButton"
        login_url = "https://nav17.stv-fsg.ch/DynamicsNAV100-NAVUser/WebClient/SignIn.aspx?ReturnUrl=%2fDynamicsNAV100-NAVUser%2fWebClient%2f"
        self.client.get(login_url)
        user = self.client.find_element(By.NAME, login_user_name)
        user.send_keys(self.creds.client_id)
        pwd = self.client.find_element(By.NAME, login_pwd_name)
        pwd.send_keys(self.creds.client_secret)
        self.client.find_element(By.NAME, login_submit_name).click()
        
    def _initiate_download(self):
        self.client.find_element(By.XPATH, "//li[contains(@class, 'ms-cui-tt')]/a[contains(@title, 'Bericht')]").click() #Bericht
        self.client.find_element(By.XPATH, "//span[@class='ms-cui-ctl-largelabel' and text()='Mitgliederverwaltung']/ancestor::a[@class='ms-cui-ctl-large']").click() #Mitgliederverwaltung
        time.sleep(3)
        self.client.find_element(By.XPATH, "//span[@class='ms-cui-ctl-largelabel' and text()='Exportieren']/ancestor::a[@class='ms-cui-ctl-large']").click() #Exportieren
        time.sleep(1)
        self.client.find_elements(By.XPATH, "//span[@class='ms-cui-tt-span' and text()='Aktionen']/ancestor::a[@class='ms-cui-tt-a']/ancestor::li[@class='ms-cui-tt ']")[1].click() #Aktionen
        self.client.find_elements(By.XPATH, "//a[@class='ms-cui-ctl-large' and .//span[@class='ms-cui-ctl-largelabel' and contains(normalize-space(), 'Alle') and contains(normalize-space(), 'auswählen')]]")[0].click() #alle auwählen
        self.client.find_elements(By.XPATH, "//span[@class='ms-cui-tt-span' and text()='Start']/ancestor::a[@class='ms-cui-tt-a']/ancestor::li[@class='ms-cui-tt ']")[0].click() #Start
        self.client.find_elements(By.XPATH, "//span[@class='ms-cui-ctl-largelabel' and text()='Exportieren']/ancestor::a[@class='ms-cui-ctl-large']")[1].click() #Exportieren

    def create_temporary_download_folder(self):
        if os.path.isdir(self.download_location):
            shutil.rmtree(self.download_location)
        os.mkdir(self.download_location)
        
    def temp_folder_contains_xlsx(self):
        files = os.listdir(self.download_location)
        for file in files:
            if file[-4:]=="xlsx":
                time.sleep(1)
                return True
        return False

    
    def move_file_to_folder(self, folder):
        files = os.listdir(self.download_location)
        files = [file for file in files if "xlsx" in file]
        assert len(files)==1
        filename = files[0]
        os.rename(os.path.join(self.download_location,filename),os.path.join(folder,filename))
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
                