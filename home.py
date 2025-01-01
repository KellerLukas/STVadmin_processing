import os
import signal
import pandas as pd
import streamlit as st

from src.STVAdmin_export_client import STVAdminExportClient

# Setting up page with branding colors
def setup_page():
    st.set_page_config(page_title="STVAdmin Export")
    st.markdown(
        """
        <style>
        body {
            background-color: white;
            color: #878787;
        }
        h1 {
            font-size: 36px;
            font-family: 'Montserrat', sans-serif;
            color: #a7353a;
        }
        h2 {
            font-size: 28px;
            font-family: 'Montserrat', sans-serif;
            color: #a7353a;
        }
        .stButton button {
            background-color: white;
            color: black;
            border-radius: 12px;
            border-color: black;
            padding: 10px 20px;
            font-size: 16px;
            transition: background-color 0.3s, box-shadow 0.3s;
        }
        .stButton button:hover {
            color: #a7353a;
            border-color: #a7353a;
            box-shadow: 0px 4px 10px rgba(0, 0, 0, 0.2);
        }
        .stToast {
            background-color: white;
            color: #a7353a;
            border-color: #a7353a;
            border-radius: 12px;
            padding: 10px;
            box-shadow: 0px 4px 15px rgba(0, 0, 0, 0.1);
        }
        .stToast-error {
            background-color: #ff4d4d;
        }
        .section-divider {
            border-top: 1px solid #878787;
            margin: 20px 0;
        }
        .section-spacing {
            margin: 40px 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# Title and header configuration
def configure_title():
    st.markdown("# STVAdmin Export")
    st.markdown("Export various lists from STVAdmin")
    if data_is_available():
        st.markdown("### Statistics")
        st.markdown(st.session_state.client.get_statistics())
    
def configure_download_data():
    st.markdown("## Setup", unsafe_allow_html=True)
    if not data_is_available():
        st.markdown("Retrieve the data from the Microsoft Dynamics Database")
        if st.button(label="Download data"):
            st.toast("Downloading data...")
            st.session_state.client.main_db
            st.toast("Finished downloading data.")
            st.rerun()
    else:
        st.markdown("Reset and retrieve new data from Microsoft Dynamics Database")
        if st.button(label="Reset"):
            reset_client()
            st.rerun()
    
    # Section divider and spacing
    st.markdown('<div class="section-spacing"></div>', unsafe_allow_html=True)
    
def configure_export_buttons():
    st.markdown("## Export", unsafe_allow_html=True)
    if not data_is_available():
        st.markdown("Data is not available")
        return

    # Button status trackers in session state
    if 'success_buttons' not in st.session_state:
        st.session_state.success_buttons = {}

    # Button grid for other exports
    col1, col2 = st.columns(2)
    with col1:
        if st.button(label="CleverReach Data", key="btn_cleverreach"):
            st.session_state.client.export_cleverreach_csv()
            st.toast("Exported CleverReach Data")

        if st.button(label="Riegenlisten", key="btn_riegenlisten"):
            st.session_state.client.export_riegenlisten_excel()
            st.toast("Exported riegenlisten")

    with col2:
        if st.button(label="No Mail", key="btn_no_mail"):
            st.session_state.client.export_no_mail_excel()
            st.toast("Exported No Mail")

        if st.button(label="Ehrenmitglieder No Mail", key="btn_ehrenmitglieder"):
            st.session_state.client.export_ehrenmitglieder_no_mail_people_excel()
            st.toast("Exported Ehrenmitglieder No Mail")

    # Year input and button alignment
    st.markdown("Export GV Lists by Year:")
    input_col, button_col = st.columns([3, 1])  # Two-column layout: wide input, narrow button

    with input_col:
        # Use default Streamlit label behavior
        gv_year = st.text_input(
            "GV lists for year:",
            value="",
            max_chars=4,
            placeholder=str(pd.Timestamp.now().year),
            label_visibility="collapsed"
        )

    with button_col:
        export_clicked = st.button(label="Export", key="export_gv_button")
        if export_clicked:
            if gv_year.isdigit() and len(gv_year) == 4:
                st.session_state.client.export_gv_lists(int(gv_year))
                st.toast(f"Exported GV lists for year {gv_year}.")
            else:
                st.error("Please enter a valid 4-digit year.")

    # Section divider and spacing
    st.markdown('<div class="section-spacing"></div>', unsafe_allow_html=True)

def reset_client():
    if isinstance(st.session_state.client, STVAdminExportClient):
        del st.session_state.client
    st.session_state.client = STVAdminExportClient(keep_files=False)
    
def data_is_available():
    if st.session_state.client._userlist_filename is None or st.session_state.client._riegenlist_filename is None:
        return False
    return True

def configure_stop():
    st.markdown('<div class="section-spacing"></div>', unsafe_allow_html=True)
    st.markdown('<hr style="border:1px solid #e0e0e0; margin:10px 0;">', unsafe_allow_html=True)


    if st.button("Shut down"):
        os.kill(os.getpid(), signal.SIGTERM)
        
        
def main():
    if "client" not in st.session_state:
        st.session_state.client = STVAdminExportClient(debugging_mode=False)
    setup_page()
    configure_title()
    configure_download_data()
    configure_export_buttons()
    configure_stop()

if __name__ == "__main__":
    main()
