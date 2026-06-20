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
    geolocator = Nominatim(user_agent="roroute_dispecerat_v7_final")
    
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

# --- Core Routing Algorithm ---
def generate_optimized_routes(orders_df, df_active_couriers, original_columns):
    orders = orders_df.copy()
    
    # Adăugăm coloanele de sistem ca tip obiect
    for col in ['Curier_Sist', 'Interval_Sist', 'Secventa', 'Ora_estimata_sosire', 'Link_navigatie', 'Status_Geocode', 'Latitudine', 'Longitudine']:
        orders[col] = ""
        orders[col] = orders[col].astype(object)

    # 1. Geocodare adrese din tabelul de comenzi folosind coloana mapată intern 'Adresa_Sist'
    with st.spinner("Geocodare și localizare adrese clienți..."):
        for idx, row in orders.iterrows():
            lat, lon, geo_addr, id_type = geocode_address_bulletproof(row['Adresa_Sist'])
            orders.at[idx, 'Latitudine'] = lat
            orders.at[idx, 'Longitudine'] = lon
            orders.at[idx, 'Status_Geocode'] = id_type

    # 2. Geocodare puncte de start pentru curieri
    c_coords = {}
    for idx, row in df_active_couriers.iterrows():
        lat_s, lon_s, _, _ = geocode_address_bulletproof(row['Punct_plecare'])
        c_coords[row['Curier_ID']] = {'start_lat': lat_s, 'start_lon': lon_s}

    courier_tracks = {c_row['Curier_ID']: [] for _, c_row in df_active_couriers.iterrows()}
    courier_counts = {c_row['Curier_ID']: 0 for _, c_row in df_active_couriers.iterrows()}
    unassigned_orders = orders.to_dict('records')
    unroutable = pd.DataFrame(columns=orders.columns)
    
    # 3. Alocare geografică (Maxim 20 comenzi/om)
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
                
                if len(courier_tracks[c_id]) > 0:
                    last_stop = courier_tracks[c_id][-1]
                    dist_to_last_stop = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], last_stop['Latitudine'], last_stop['Longitudine'])
                else:
                    dist_to_last_stop = dist_from_start
                
                score = (dist_from_start * 0.4) + (dist_to_last_stop * 0.6) + (courier_counts[c_id] * 2.0)
                
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
        unroutable = pd.concat([unroutable, pd.DataFrame([left_item])], ignore_index=True)

    # 4. Secvențiere trasee și calcul timpi (Plecare la 09:30)
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
            travel_time_min = (dist / 30.0) * 60.0
            
            current_time += timedelta(minutes=travel_time_min)
            arrival_time_str = current_time.strftime("%H:%M")
            
            rounded_hour = current_time.hour
            applied_slot = f"{rounded_hour:02d}:00-{(rounded_hour + 2):02d}:00"
            
            # Populăm exact coloanele capătului tău de tabel original
            stop['Curier'] = c_row['Nume_curier']
            stop['Interval Livrare'] = applied_slot
            
            stop['Secventa'] = seq
            stop['Ora_estimata_sosire'] = arrival_time_str
            stop['Link_navigatie'] = f"http://maps.google.com/?q={stop['Latitudine']},{stop['Longitudine']}"
            
            final_route_records.append(stop)
            current_time += timedelta(minutes=20)

    df_final_output = pd.DataFrame(final_route_records) if final_route_records else pd.DataFrame()
    if not df_final_output.empty and not unroutable.empty:
        df_final_output = pd.concat([df_final_output, unroutable], ignore_index=True)
    elif df_final_output.empty:
        df_final_output = unroutable

    review_needed = df_final_output[df_final_output['Status_Geocode'].isin(['Aproximat Localitate', 'Necesită Atenție'])]
    
    # Asigurăm exportul fix în formatul tău original
    existing_columns = [c for c in original_columns if c in df_final_output.columns]
    return df_final_output[existing_columns], review_needed, df_final_output

# --- UI Interface ---
st.title("🚚 RoRoute - Panificator Inteligent de Livrări")
st.subheader("Sincronizare automată tabel comenzi și configurație curieri")

st.sidebar.markdown("### 📋 Încărcare Documente")
uploaded_orders = st.sidebar.file_uploader("1. Încarcă Tabel Comenzi (Excel/CSV)", type=["csv", "xlsx"])
uploaded_couriers = st.sidebar.file_uploader("2. Încarcă Configurație Curieri (.csv)", type=["csv"])

df_orders_raw = None
df_couriers_raw = None
original_cols = []

if uploaded_orders:
    df_orders_raw = pd.read_csv(uploaded_orders) if uploaded_orders.name.endswith('.csv') else pd.read_excel(uploaded_orders)
    # Curățăm denumirile coloanelor brute de spații
    df_orders_raw.columns = [str(c).strip() for c in df_orders_raw.columns]
    original_cols = list(df_orders_raw.columns)
    
    # FIX PENTRU KEYERROR: Mapare flexibilă pentru coloana Adresa
    if 'Adresa' not in df_orders_raw.columns:
        for alternative in ['Adresă', 'Address', 'Full Address', 'Adresa livrare']:
            if alternative in df_orders_raw.columns:
                df_orders_raw['Adresa_Sist'] = df_orders_raw[alternative]
                break
    else:
        df_orders_raw['Adresa_Sist'] = df_orders_raw['Adresa']

if uploaded_couriers:
    df_couriers_raw = pd.read_csv(uploaded_couriers, sep=";")
    df_couriers_raw.columns = [str(c).strip() for c in df_couriers_raw.columns]
    df_couriers_raw = df_couriers_raw.dropna(subset=['Curier_ID', 'Nume_curier'])

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

if df_orders_raw is not None and not active_couriers_df.empty:
    st.success(f"📊 Date pregătite! {len(df_orders_raw)} comenzi detectate și {len(active_couriers_df)} curieri activi.")
    
    if st.button("🚀 Generează și Optimizează Traseele pe Hartă", type="primary"):
        # Verificăm din nou existența coloanei mapate
        if 'Adresa_Sist' not in df_orders_raw.columns:
            st.error("❌ Nu am putut identifica coloana cu adresele de livrare în fișierul tău. Asigură-te că se numește 'Adresa'.")
        else:
            routes_final, review_df, full_tech_df = generate_optimized_routes(df_orders_raw, active_couriers_df, original_cols)
            
            if routes_final is not None and not routes_final.empty:
                st.success("✅ Optimizare finalizată!")
                
                # --- AFIȘARE HARTĂ INTERACTIVĂ ---
                st.markdown("### 🗺️ Vizualizare Trasee pe Hartă Interactivă")
                map_clean_df = full_tech_df[full_tech_df['Curier'].notna() & (full_tech_df['Curier'] != "")]
                if not map_clean_df.empty:
                    map_render = map_clean_df[['Latitudine', 'Longitudine']].dropna().rename(columns={'Latitudine': 'latitude', 'Longitudine': 'longitude'})
                    st.map(map_render)
                
                kpi_cols = st.columns(3)
                kpi_cols[0].metric("Total Livrări Alocate", len(map_clean_df))
                kpi_cols[1].metric("Curieri pe Traseu", map_clean_df['Curier'].nunique())
                kpi_cols[2].metric("Adrese de Verificat", len(review_df))
                
                if len(review_df) > 0:
                    st.warning("⚠️ Adrese identificate aproximativ:")
                    st.dataframe(review_df[['Nr. Comanda', 'First Name (Shipping)', 'Last Name (Shipping)', 'Adresa_Sist', 'Status_Geocode']], use_container_width=True)
                    
                st.markdown("### 🗺️ Ordinea Livrărilor (Format identic cu fișierul original)")
                st.dataframe(routes_final, use_container_width=True)
                
                csv_buffer = io.StringIO()
                routes_final.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📥 Descarcă Fișierul de Trasee Final",
                    data=csv_buffer.getvalue(),
                    file_name=f"Trasee_Livrare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
else:
    st.info("💡 Pentru a începe, încarcă tabelul cu comenzi și tabelul de curieri în bara laterală stângă, apoi bifează cine livrează astăzi.")
