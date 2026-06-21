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
    geolocator = Nominatim(user_agent="roroute_dispecerat_v8_manual")
    
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
    for idx, c in enumerate(df.columns):
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
    return mapped_cols

# --- Core Routing Algorithm ---
def generate_optimized_routes(orders_df, df_active_couriers, original_columns, mapped_fields):
    orders = orders_df.copy()
    
    for col in ['Secventa', 'Ora_estimata_sosire', 'Link_navigatie', 'Status_Geocode', 'Latitudine', 'Longitudine']:
        if col not in orders.columns:
            orders[col] = ""
            orders[col] = orders[col].astype(object)

    addr_col_name = mapped_fields.get('Adresa')

    with st.spinner("Geocodare și localizare adrese clienți..."):
        for idx, row in orders.iterrows():
            lat, lon, geo_addr, id_type = geocode_address_bulletproof(row[addr_col_name])
            orders.at[idx, 'Latitudine'] = lat
            orders.at[idx, 'Longitudine'] = lon
            orders.at[idx, 'Status_Geocode'] = id_type

    c_coords = {}
    for idx, row in df_active_couriers.iterrows():
        lat_s, lon_s, _, _ = geocode_address_bulletproof(row['Punct_plecare'])
        c_coords[row['Curier_ID']] = {'start_lat': lat_s, 'start_lon': lon_s}

    courier_tracks = {c_row['Curier_ID']: [] for _, c_row in df_active_couriers.iterrows()}
    courier_counts = {c_row['Curier_ID']: 0 for _, c_row in df_active_couriers.iterrows()}
    unassigned_orders = orders.to_dict('records')
    leftovers_list = []
    
    # Repartizare geografică optimizată cu penalizare crescută pentru echilibrare corectă
    while len(unassigned_orders) > 0:
        best_score = float('inf')
        best_courier = None
        best_order_idx = None
        
        for idx, ord_item in enumerate(unassigned_orders):
            for _, c_row in df_active_couriers.iterrows():
                c_id = c_row['Curier_ID']
                max_cap = int(c_row.get('Capacitate_max_livrari', 20))
                if courier_counts[c_id] >= max_cap:
                    continue
                    
                c_loc = c_coords[c_id]
                dist_from_start = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], c_loc['start_lat'], c_loc['start_lon'])
                dist_to_last_stop = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], courier_tracks[c_id][-1]['Latitudine'], courier_tracks[c_id][-1]['Longitudine']) if len(courier_tracks[c_id]) > 0 else dist_from_start
                
                # FIX: Creșterea factorului de penalizare la 15.0 forțează algoritmul să distribuie egal pe cei 3 curieri
                score = (dist_from_start * 0.3) + (dist_to_last_stop * 0.7) + (courier_counts[c_id] * 15.0)
                if score < best_score:
                    best_score = score
                    best_courier = c_id
                    best_order_idx = idx
                    
        if best_courier is None:
            break
            
        chosen_order = unassigned_orders.pop(best_order_idx)
        chosen_order['Curier_alocat_id'] = best_courier
        courier_tracks[best_courier].append(chosen_order)
        courier_counts[best_courier] += 1

    for left_item in unassigned_orders:
        left_item['Status_Geocode'] = 'Nefinalizat - Capacitate Depășită'
        leftovers_list.append(left_item)

    final_route_records = []
    for _, c_row in df_active_couriers.iterrows():
        c_id = c_row['Curier_ID']
        track = courier_tracks[c_id]
        if not track:
            continue
            
        sequenced_track = []
        curr_lat, curr_lon = c_coords[c_id]['start_lat'], c_coords[c_id]['start_lon']
        while len(track) > 0:
            next_idx = min(range(len(track)), key=lambda i: haversine_distance(curr_lat, curr_lon, track[i]['Latitudine'], track[i]['Longitudine']))
            next_stop = track.pop(next_idx)
            sequenced_track.append(next_stop)
            curr_lat, curr_lon = next_stop['Latitudine'], next_stop['Longitudine']

        current_time = datetime.strptime("09:30", "%H:%M")
        for seq, stop in enumerate(sequenced_track, start=1):
            if seq == 1:
                prev_lat, prev_lon = c_coords[c_id]['start_lat'], c_coords[c_id]['start_lon']
            else:
                prev_lat, prev_lon = sequenced_track[seq-2]['Latitudine'], sequenced_track[seq-2]['Longitudine']
                
            dist = haversine_distance(prev_lat, prev_lon, stop['Latitudine'], stop['Longitudine'])
            current_time += timedelta(minutes=((dist / 30.0) * 60.0))
            
            rounded_hour = current_time.hour
            applied_slot = f"{rounded_hour:02d}:00-{(rounded_hour + 2):02d}:00"
            
            if 'Curier' in mapped_fields:
                stop[mapped_fields['Curier']] = c_row['Nume_curier']
            if 'Interval Livrare' in mapped_fields:
                stop[mapped_fields['Interval Livrare']] = applied_slot
            
            stop['Secventa'] = seq
            stop['Ora_estimata_sosire'] = current_time.strftime("%H:%M")
            stop['Link_navigatie'] = f"http://maps.google.com/?q={stop['Latitudine']},{stop['Longitudine']}"
            final_route_records.append(stop)
            current_time += timedelta(minutes=20)

    df_routed = pd.DataFrame(final_route_records) if final_route_records else pd.DataFrame(columns=orders.columns)
    df_leftovers = pd.DataFrame(leftovers_list) if leftovers_list else pd.DataFrame(columns=orders.columns)
    df_final_output = pd.concat([df_routed, df_leftovers], ignore_index=True) if not df_routed.empty else df_leftovers

    review_needed = df_final_output[df_final_output['Status_Geocode'].isin(['Aproximat Localitate', 'Necesită Atenție'])]
    return df_final_output, review_needed

# --- UI Interface ---
st.title("🚚 RoRoute - Centrală de Dispecerat și Alocare Manuală")
st.subheader("Modifică adresele direct pe ecran sau reatribui manual curierii")

st.sidebar.markdown("### 📋 Încărcare Documente")
uploaded_orders = st.sidebar.file_uploader("1. Încarcă Tabel Comenzi (Excel/CSV)", type=["csv", "xlsx"])
uploaded_couriers = st.sidebar.file_uploader("2. Încarcă Configurație Curieri (.csv)", type=["csv"])

if 'orders_df' not in st.session_state:
    st.session_state.orders_df = None
if 'couriers_list' not in st.session_state:
    st.session_state.couriers_list = []

df_couriers_raw = None
if uploaded_couriers:
    courier_bytes = uploaded_couriers.read()
    courier_text = courier_bytes.decode('utf-8', errors='ignore')
    courier_text_clean = re.sub(r'^,+;', 'Curier_ID;', courier_text, flags=re.MULTILINE)
    df_couriers_raw = pd.read_csv(io.StringIO(courier_text_clean), sep=";")
    df_couriers_raw.columns = [str(c).strip() for c in df_couriers_raw.columns]
    df_couriers_raw = df_couriers_raw.dropna(subset=['Curier_ID', 'Nume_curier'])
    st.session_state.couriers_list = list(df_couriers_raw['Nume_curier'].unique())

active_couriers_df = pd.DataFrame()
if df_couriers_raw is not None:
    st.sidebar.markdown("### 🛵 Selectează Curierii Activi Azi:")
    selected_couriers = []
    for idx, row in df_couriers_raw.iterrows():
        is_active = st.sidebar.checkbox(f"🛵 {row['Nume_curier']}", value=True, key=f"c_{row['Curier_ID']}")
        if is_active:
            selected_couriers.append(row)
    if selected_couriers:
        active_couriers_df = pd.DataFrame(selected_couriers)

if uploaded_orders:
    if st.session_state.orders_df is None:
        df_raw = pd.read_csv(uploaded_orders) if uploaded_orders.name.endswith('.csv') else pd.read_excel(uploaded_orders)
        df_raw.columns = [str(c).strip() for c in df_raw.columns]
        st.session_state.orders_df = df_raw

if st.session_state.orders_df is not None and not active_couriers_df.empty:
    mapped_fields = map_columns_robustly(st.session_state.orders_df)
    
    st.markdown("### 📝 1. Corectare Erori Text (Fă dublu-click pe orice celulă pentru a edita adresele)")
    # Sistem avansat Streamlit Data Editor care îți permite să editezi live erorile
    edited_df = st.data_editor(st.session_state.orders_df, use_container_width=True, num_rows="dynamic")
    st.session_state.orders_df = edited_df

    if st.button("🚀 Pasul 2: Lansează Optimizarea Geografică Trasee", type="primary"):
        original_cols = list(st.session_state.orders_df.columns)
        optimized_res, review_df = generate_optimized_routes(st.session_state.orders_df, active_couriers_df, original_cols, mapped_fields)
        st.session_state.optimized_res = optimized_res
        st.session_state.review_df = review_df
        st.success("✅ Rutele inițiale au fost calculate geografic și echilibrat!")

    # Verificăm dacă avem rute calculate gata de afișare și ajustare manuală
    if 'optimized_res' in st.session_state:
        st.markdown("### 🗺️ Vizualizare Trasee pe Hartă Interactivă")
        map_clean = st.session_state.optimized_res[st.session_state.optimized_res['Latitudine'].notna()]
        if not map_clean.empty:
            st.map(map_clean[['Latitudine', 'Longitudine']].rename(columns={'Latitudine': 'latitude', 'Longitudine': 'longitude'}))

        st.markdown("### ⚙️ 2. Ajustare și Alocare Manuală Curieri / Trasee")
        st.info("💡 Poți schimba manual Curierul sau Intervalul direct din tabelul de mai jos pentru a forța modificarea unui traseu:")
        
        # Configurăm regulile de editare manuală prin liste drop-down controlate
        column_config = {}
        if 'Curier' in mapped_fields:
            column_config[mapped_fields['Curier']] = st.column_config.SelectboxColumn("Curier Alocat", options=st.session_state.couriers_list, width="medium")
        if 'Interval Livrare' in mapped_fields:
            column_config[mapped_fields['Interval Livrare']] = st.column_config.SelectboxColumn("Fereastră Livrare", options=["10:00-12:00", "11:00-13:00", "12:00-14:00", "13:00-15:00", "14:00-16:00", "15:00-17:00", "16:00-18:00"], width="medium")
            
        final_adjusted_df = st.data_editor(st.session_state.optimized_res, use_container_width=True, column_config=column_config)
        
        # Curățăm coloanele tehnice pentru ca fișierul descărcat să aibă fix formatul tău original curat
        clean_cols_to_download = [c for c in list(st.session_state.orders_df.columns) if c in final_adjusted_df.columns]
        download_ready_df = final_adjusted_df[clean_cols_to_download]

        csv_buffer = io.StringIO()
        download_ready_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
        st.download_button
