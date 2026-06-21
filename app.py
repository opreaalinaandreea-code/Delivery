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
    return mapped_cols

# --- Core Routing Algorithm ---
def generate_optimized_routes(orders_df, df_active_couriers, original_columns):
    orders = orders_df.copy()
    
    # FIX INDREPTARE PENTRU KEYERROR: Maparea rulează direct în funcție pe setul proaspăt de date primit
    mapped_fields = map_columns_robustly(orders)
    addr_col_name = mapped_fields.get('Adresa', 'Adresa')
    
    orders['Latitudine'] = np.nan
    orders['Longitudine'] = np.nan
    orders['Status_Geocode'] = "Negeocodat"

    # 1. Geocodare adrese din tabelul de comenzi
    with st.spinner("Geocodare și localizare adrese clienți..."):
        for idx, row in orders.iterrows():
            lat, lon, _, id_type = geocode_address_bulletproof(row[addr_col_name])
            orders.at[idx, 'Latitudine'] = lat
            orders.at[idx, 'Longitudine'] = lon
            orders.at[idx, 'Status_Geocode'] = id_type

    # 2. Geocodare puncte de start pentru curieri
    c_coords = {}
    for idx, row in df_active_couriers.iterrows():
        lat_s, lon_s, _, _ = geocode_address_bulletproof(row['Punct_plecare'])
        c_coords[row['Curier_ID']] = {'start_lat': lat_s, 'start_lon': lon_s, 'name': row['Nume_curier']}

    # 3. Clustering / Alocare Geografică Echilibrată
    unassigned_orders = orders.to_dict('records')
    courier_lists = {c_id: [] for c_id in c_coords.keys()}
    
    unassigned_orders.sort(key=lambda x: haversine_distance(x['Latitudine'], x['Longitudine'], 44.4325, 26.1001))
    
    for ord_item in unassigned_orders:
        best_c = None
        best_dist = float('inf')
        
        for c_id, c_loc in c_coords.items():
            if len(courier_lists[c_id]) >= 20: 
                continue
            
            if len(courier_lists[c_id]) > 0:
                base_lat = courier_lists[c_id][-1]['Latitudine']
                base_lon = courier_lists[c_id][-1]['Longitudine']
            else:
                base_lat = c_loc['start_lat']
                base_lon = c_loc['start_lon']
                
            dist = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], base_lat, base_lon)
            # Penalizare mărită (12.0) garantează că adresele se împart uniform pe Alina, Corina și Marius
            score = dist + (len(courier_lists[c_id]) * 12.0)
            
            if score < best_dist:
                best_dist = score
                best_c = c_id
                
        if best_c is not None:
            courier_lists[best_c].append(ord_item)

    # 4. Secvențiere rute și generare intervale orare
    final_records = []
    for c_id, track in courier_lists.items():
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
                stop[mapped_fields['Curier']] = c_coords[c_id]['name']
            if 'Interval Livrare' in mapped_fields:
                stop[mapped_fields['Interval Livrare']] = applied_slot
            
            final_records.append(stop)
            current_time += timedelta(minutes=20)

    df_final = pd.DataFrame(final_records) if final_records else pd.DataFrame(columns=orders.columns)
    return df_final

# --- UI Interface ---
st.title("🚚 RoRoute - Centrală Operativă de Dispecerat")
st.subheader("Editare live adrese, alocare manuală pe agenți și vizualizare hartă fixată")

st.sidebar.markdown("### 📋 Încărcare Documente")
uploaded_orders = st.sidebar.file_uploader("1. Încarcă Tabel Comenzi (Excel/CSV)", type=["csv", "xlsx"])
uploaded_couriers = st.sidebar.file_uploader("2. Încarcă Configurație Curieri (.csv)", type=["csv"])

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
        is_active = st.sidebar.checkbox(f"🛵 {row['Nume_curier']} ({row['Zona_preferata']})", value=True, key=f"c_{row['Curier_ID']}")
        if is_active:
            selected_couriers.append(row)
    if selected_couriers:
        active_couriers_df = pd.DataFrame(selected_couriers)

if uploaded_orders and st.session_state.orders_df is None:
    df_raw = pd.read_csv(uploaded_orders) if uploaded_orders.name.endswith('.csv') else pd.read_excel(uploaded_orders)
    df_raw.columns = [str(c).strip() for c in df_raw.columns]
    st.session_state.orders_df = df_raw

if st.session_state.orders_df is not None and not active_couriers_df.empty:
    mapped_fields = map_columns_robustly(st.session_state.orders_df)
    
    st.markdown("### 📝 1. Corectare Erori Text (Dublu-click pe celule pentru a edita adresele live)")
    edited_df = st.data_editor(st.session_state.orders_df, use_container_width=True, key="comenzi_editor")
    
    if st.button("🚀 Pasul 2: Calculează Distribuția și Traseele Optimizate", type="primary"):
        original_cols = list(edited_df.columns)
        st.session_state.final_display_df = generate_optimized_routes(edited_df, active_couriers_df, original_cols)
        st.success("✅ Rutele au fost calculate echilibrat pe toți curierii activi!")

    if st.session_state.final_display_df is not None:
        curier_col = mapped_fields.get('Curier', 'Curier')
        interval_col = mapped_fields.get('Interval Livrare', 'Interval Livrare')

        st.markdown("### ⚙️ 2. Panou Ajustare și Alocare Manuală Curieri")
        st.info("💡 Poți schimba manual Curierul sau Intervalul direct din tabel. Schimbările vor muta instant pinii pe harta de mai jos:")
        
        column_config = {}
        if curier_col in st.session_state.final_display_df.columns:
            column_config[curier_col] = st.column_config.SelectboxColumn("Curier Alocat", options=st.session_state.couriers_list, width="medium")
        if interval_col in st.session_state.final_display_df.columns:
            column_config[interval_col] = st.column_config.SelectboxColumn("Fereastră Orare", options=["09:00-11:00", "10:00-12:00", "11:00-13:00", "12:00-14:00", "13:00-15:00", "14:00-16:00", "15:00-17:00", "16:00-18:00"], width="medium")
            
        adjusted_final_df = st.data_editor(st.session_state.final_display_df, use_container_width=True, column_config=column_config, key="ajustare_parcurs_final")
        
        # --- VIZUALIZARE HARTĂ INTERACTIVĂ DINAMICĂ ---
        st.markdown("### 🗺️ Vizualizare Trasee pe Hartă Interactivă")
        map_data = adjusted_final_df[['Latitudine', 'Longitudine']].dropna().rename(columns={'Latitudine': 'latitude', 'Longitudine': 'longitude'})
        if not map_data.empty:
            st.map(map_data)
            
        # KPI Informative
        kpi_cols = st.columns(3)
        kpi_cols[0].metric("Total Comenzi Alocate", len(adjusted_final_df))
        kpi_cols[1].metric("Curieri Pe Traseu", adjusted_final_df[curier_col].dropna().nunique() if curier_col in adjusted_final_df.columns else 0)
        kpi_cols[2].metric("Plafon Maxim Adrese / Om", "20 pachete")

        # Păstrăm exclusiv capătul de tabel original pentru fișierul descărcat
        original_base_cols = list(st.session_state.orders_df.columns)
        clean_download_df = adjusted_final_df[[c for c in original_base_cols if c in adjusted_final_df.columns]]

        csv_buffer = io.StringIO()
        clean_download_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
        st.download_button(
            label="📥 Descarcă Fișierul Final Ajustat Operativ",
            data=csv_buffer.getvalue(),
            file_name="Trasee_Sincronizate_Respectate.csv",
            mime="text/csv"
        )
else:
    st.info("💡 Pentru a începe, încarcă tabelul cu comenzi și fișierul 'curieri bun.csv' în bara laterală stângă.")
