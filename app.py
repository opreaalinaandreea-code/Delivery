import streamlit as st
import pandas as pd
import numpy as np
import math
import re
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
import io

# --- Page Configuration ---
st.set_page_config(page_title="RoRoute - Dispecerat Avansat", layout="wide")

if 'geocoding_cache' not in st.session_state:
    st.session_state.geocoding_cache = {}
if 'orders_df' not in st.session_state:
    st.session_state.orders_df = None
if 'couriers_list' not in st.session_state:
    st.session_state.couriers_list = []
if 'final_display_df' not in st.session_state:
    st.session_state.final_display_df = None

# --- Algoritm de curățare adrese din România ---
def clean_romanian_address(address_text):
    if not address_text or pd.isna(address_text):
        return ""
    addr = str(address_text).lower().strip()
    addr = re.sub(r'\bbl\b|\bbloc\b.*', '', addr)
    addr = re.sub(r'\bsc\b|\bscara\b.*', '', addr)
    addr = re.sub(r'\bap\b|\bapartament\b.*', '', addr)
    addr = re.sub(r'\bet\b|\betaj\b.*', '', addr)
    addr = re.sub(r'\binterfon\b.*', '', addr)
    addr = re.sub(r'\bsos\b|\bşos\b|\bsoseaua\b', 'soseaual', addr)
    addr = re.sub(r'\bstr\b|\bstrada\b', 'strada', addr)
    addr = re.sub(r'\bbd\b|\bblv\b|\bbvd\b|\bbulevardul\b', 'bulevardul', addr)
    addr = re.sub(r'\bcal\b|\bcalea\b', 'calea', addr)
    addr = re.sub(r'\bint\b|\bintrarea\b', 'intrarea', addr)
    addr = re.sub(r'\bprel\b|\bprelungirea\b', 'prelungirea', addr)
    addr = re.sub(r'(\d+)-\d+', r'\1', addr)
    addr = addr.replace('ş', 's').replace('ţ', 't').replace('ă', 'a').replace('î', 'i').replace('â', 'a')
    return addr.strip().title()

def extract_locality_fallback(address_text):
    if not address_text or pd.isna(address_text):
        return "Bucuresti"
    parts = str(address_text).split(',')
    if len(parts) > 0:
        loc = parts[0].strip().title()
        return loc if len(loc) > 2 else "Bucuresti"
    return "Bucuresti"

def geocode_address_bulletproof(address_raw):
    if not address_raw or pd.isna(address_raw) or str(address_raw).strip() == "":
        return 44.4325, 26.1001, "Adresă Lipsă", "Punct Default"
    addr_str = str(address_raw).strip()
    if addr_str in st.session_state.geocoding_cache:
        return st.session_state.geocoding_cache[addr_str]
        
    clean_addr = clean_romanian_address(addr_str)
    query_full = clean_addr if "romania" in clean_addr.lower() else f"{clean_addr}, Romania"
    geolocator = Nominatim(user_agent="roroute_dispecerat_v9_stable")
    
    try:
        location = geolocator.geocode(query_full, timeout=5)
        if location:
            res = (location.latitude, location.longitude, location.address, "Geocodat Complet")
            st.session_state.geocoding_cache[addr_str] = res
            return res
    except Exception:
        pass
        
    locality = extract_locality_fallback(addr_str)
    query_loc = f"{locality}, Romania"
    try:
        location = geolocator.geocode(query_loc, timeout=4)
        if location:
            res = (location.latitude, location.longitude, f"Aproximat în: {location.address}", "Aproximat Localitate")
            st.session_state.geocoding_cache[addr_str] = res
            return res
    except Exception:
        pass
        
    res = (44.4325, 26.1001, "Localizare eșuată - Hub", "Necesită Atenție")
    st.session_state.geocoding_cache[addr_str] = res
    return res

def haversine_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2) or any(math.isnan(x) for x in (lat1, lon1, lat2, lon2)):
        return 999.0
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def map_columns_robustly(df):
    mapped_cols = {}
    for c in df.columns:
        c_clean = str(c).strip().lower()
        if 'adresa' in c_clean or 'address' in c_clean or 'locatie' in c_clean:
            mapped_cols['Adresa'] = c
        elif 'comanda' in c_clean or 'order' in c_clean or 'id' in c_clean:
            mapped_cols['Nr. Comanda'] = c
        elif 'first' in c_clean or 'nume' in c_clean:
            mapped_cols['First Name'] = c
        elif 'last' in c_clean or 'prenume' in c_clean:
            mapped_cols['Last Name'] = c
        elif 'phone' in c_clean or 'telefon' in c_clean or 'tel' in c_clean:
            mapped_cols['Telefon'] = c
        elif 'curier' in c_clean:
            mapped_cols['Curier'] = c
        elif 'interval' in c_clean or 'slot' in c_clean:
            mapped_cols['Interval Livrare'] = c
    return
