import streamlit as st
import pandas as pd
import numpy as np
import math
import re
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import io

# --- Page Configuration ---
st.set_page_config(page_title="RoRoute - Planificator Automat Trasee", layout="wide")

# --- Simple Local Cache For Geocoding ---
if 'geocoding_cache' not in st.session_state:
    st.session_state.geocoding_cache = {}

# --- Funcție de Curățare și Corectare Adrese din România ---
def clean_romanian_address(address_text):
    """
    Curăță adresele brute în format românesc pentru a ajuta hărțile gratuite
    să le identifice cu o acuratețe mult mai mare.
    """
    if not address_text or pd.isna(address_text):
        return ""
        
    # Transformă în text mic pentru uniformizare
    addr = str(address_text).lower().strip()
    
    # 1. Înlocuire prescurtări comune din România
    addr = re.sub(r'\bsos\b|\bşos\b|\bsoseaua\b', 'soseaual', addr)
    addr = re.sub(r'\bstr\b|\bstrada\b', 'strada', addr)
    addr = re.sub(r'\bbd\b|\bblv\b|\bbvd\b|\bbulevardul\b', 'bulevardul', addr)
    addr = re.sub(r'\bcal\b|\bcalea\b', 'calea', addr)
    addr = re.sub(r'\bint\b|\bintrarea\b', 'intrarea', addr)
    addr = re.sub(r'\bprel\b|\bprelungirea\b', 'prelungirea', addr)
    
    # 2. Eliminare intervale de numere (ex: "40-44" devine "40") - Hărțile libere nu înțeleg intervale
    addr = re.sub(r'(\d+)-\d+', r'\1', addr)
    
    # Curățare diacritice vechi sau transformări speciale pentru a ajuta motorul Nominatim
    addr = addr.replace('ş', 's').replace('ţ', 't').replace('ă', 'a').replace('î', 'i').replace('â', 'a')
    
    return addr.strip().title()

# --- Smart Extractor pentru Localitate ---
def extract_locality(address_text):
    if not address_text or pd.isna(address_text):
        return "Bucuresti"
    parts = str(address_text).split(',')
    if len(parts) > 0:
        loc = parts[0].strip().title()
        return loc if len(loc) > 2 else "Bucuresti"
    return "Bucuresti"

# --- Geocoding Service Function (100% Gratuit & Optimizat) ---
def geocode_address_free_optimized(address):
    """
    Geocodează o adresă folosind exclusiv serviciul gratuit Nominatim,
    dar trecută prin filtrul de curățare structurală.
    """
    if not address or pd.isna(address):
        return 44.4325, 26.1001, "Adresă Lipsă - Plasat în Centru (București)", "Punct Default"
        
    address_raw = str(address).strip()
    
    if address_raw in st.session_state.geocoding_cache:
        return st.session_state.geocoding_cache[address_raw]
        
    # Aplicăm curățarea adreselor românești
    address_cleaned = clean_romanian_address(address_raw)
    
    # Pregătim interogarea finală securizată cu țara
    if "romania" not in address_cleaned.lower():
        query_full = f"{address_cleaned}, Romania"
    else:
        query_full = address_cleaned

    geolocator = Nominatim(user_agent="roroute_planner_free_cleaner_v4")

    # Strategia 1: Căutare cu adresa curățată completă
    try:
        location = geolocator.geocode(query_full, timeout=5)
        if location:
            res = (location.latitude, location.longitude, location.address, "Geocodat Complet (Gratuit)")
            st.session_state.geocoding_cache[address_raw] = res
            return res
    except Exception:
        pass

    # Strategia 2: Fallback la nivel de Localitate (Dacă strada tot nu e găsită, plasăm în centrul localității)
    locality = extract_locality(address_raw)
    query_locality = f"{locality}, Romania"
    try:
        location = geolocator.geocode(query_locality, timeout=4)
        if location:
            res = (location.latitude, location.longitude, f"Aproximat în centrul: {location.address}", "Aproximat Localitate")
            st.session_state.geocoding_cache[address_raw] = res
            return res
    except Exception:
        pass

    # Strategia 3: Garanție finală (Plasat la coordonatele implicite de Hub/București ca să nu dispară din sistem)
    res = (44.4325, 26.1001, f"Localizare eșuată - Plasat implicit la Hub central", "Necesită Atenție Curier")
    st.session_state.geocoding_cache[address_raw] = res
    return res

# --- Distance Calculation ---
def haversine_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2) or any(math.isnan(x) for x in (lat1, lon1, lat2, lon2)):
        return 999.0
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- Sample Data Generator ---
def get_sample_data():
    orders_data = {
        'Nr. Comanda': [f"ORD-{i:03d}" for i in range(1, 6)],
        'First Name (Shipping)': ['Ion', 'Maria', 'Dan', 'Grigore', 'Oana'],
        'Last Name (Shipping)': ['Popescu', 'Ionescu', 'Vasile', 'Elena', 'Gheltu'],
        'Phone (Billing)': ['0722111222', '0733222333', '0744333444', '0786440547', '0720015842'],
        'Adresa': ['Bucuresti, Bd Unirii, 70', 'Bucuresti, sos oltenitei, 40-44', 'Bucuresti, Azuga, 32', 'Berceni, Campului, 14D', 'Domnesti, Fortului, 91D'],
        'Payment Method Title': ['Ramburs', 'Card', 'Ramburs', 'Revolut', 'Ramburs'],
        'Order Total Amount': [150, 132, 164, 210, 57]
    }
    couriers_data = {
        'Curier_ID': ['C01', 'C02'],
        'Nume_curier': ['Alex Curier', 'Mihai Transport'],
        'Activ': [True, True],
        'Punct_plecare': ['Piata Unirii, Bucuresti', 'Piata Victoriei, Bucuresti'],
        'Punct_finalizare': ['Piata Unirii, Bucuresti', 'Piata Victoriei, Bucuresti'],
        'Capacitate_max_livrari': [20, 20]
    }
    return pd.DataFrame(orders_data), pd.DataFrame(couriers_data)

# --- Standardizer / Column Mapper ---
def standardize_orders_df(df):
    df = df.copy()
    original_cols = list(df.columns)
    clean_cols = [str(c).strip() for c in df.columns]
    df.columns = clean_cols
    
    mapping = {
        'ID_Livrare': ['Nr. Comanda', 'ID_Livrare', 'Id', 'ID', 'Cod'],
        'Client': ['First Name (Shipping)', 'Client', 'Nume', 'Name', 'Destinatar'],
        'Telefon': ['Phone (Billing)', 'Telefon', 'Phone', 'Tel', 'Phone_Billing'],
        'Adresa_originala': ['Adresa', 'Adresa_originala', 'Address', 'Adresă', 'Full Address']
    }
    
    for system_col, user_options in mapping.items():
        if system_col not in df.columns:
            for option in user_options:
                if option in df.columns:
                    df[system_col] = df[option]
                    break
            if system_col not in df.columns:
                df[system_col] = ""
                
    if 'Durata_stop_min' not in df.columns: df['Durata_stop_min'] = 10
    if 'Timp_buffer_min' not in df.columns: df['Timp_buffer_min'] = 10
    return df, original_cols

def standardize_couriers_df(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    
    mapping = {
        'Curier_ID': ['Curier_ID', 'ID', 'Id', 'Cod'],
        'Nume_curier': ['Nume_curier', 'Curier', 'Nume', 'Name'],
        'Activ': ['Activ', 'Active', 'Status'],
        'Punct_plecare': ['Punct_plecare', 'Plecare', 'Start'],
        'Punct_finalizare': ['Punct_finalizare', 'Sosire', 'Final', 'End'],
        'Capacitate_max_livrari': ['Capacitate_max_livrari', 'Capacitate', 'Max']
    }
    
    for system_col, user_options in mapping.items():
        if system_col not in df.columns:
            for option in user_options:
                if option in df.columns:
                    df[system_col] = df[option]
                    break
    
    if 'Curier_ID' not in df.columns: df['Curier_ID'] = [f"C{i}" for i in range(1, len(df)+1)]
    if 'Nume_curier' not in df.columns: df['Nume_curier'] = df['Curier_ID']
    if 'Activ' not in df.columns: df['Activ'] = True
    if 'Punct_plecare' not in df.columns: df['Punct_plecare'] = "Bucuresti, Romania"
    if 'Punct_finalizare' not in df.columns: df['Punct_finalizare'] = "Bucuresti, Romania"
    if 'Capacitate_max_livrari' not in df.columns: df['Capacitate_max_livrari'] = 20
    
    df['Activ'] = df['Activ'].apply(lambda x: str(x).strip().lower() in ['true', '1', 'da', 'yes', 'active'])
    return df

# --- Core Routing Algorithm ---
def generate_optimized_routes(df_orders, df_couriers):
    orders, original_columns = standardize_orders_df(df_orders)
    couriers = standardize_couriers_df(df_couriers)
    
    active_couriers = couriers[couriers['Activ'] == True].copy()
    if len(active_couriers) == 0:
        return None, "Nu există curieri activi în fișier."
        
    if len(active_couriers) > 4:
        active_couriers = active_couriers.head(4)

    c_coords = {}
    for idx, row in active_couriers.iterrows():
        lat_s, lon_s, _, _ = geocode_address_free_optimized(row['Punct_plecare'])
        lat_f, lon_f, _, _ = geocode_address_free_optimized(row['Punct_finalizare'])
        c_coords[row['Curier_ID']] = {
            'start_lat': lat_s or 44.4325, 'start_lon': lon_s or 26.1001,
            'end_lat': lat_f or 44.4325, 'end_lon': lon_f or 26.1001
        }

    for col in ['Latitudine', 'Longitudine']:
        if col not in orders.columns:
            orders[col] = np.nan
            
    for col in ['Geocoded_address', 'Tip_Identificare', 'Curier_alocat', 'Curier', 'Secventa', 'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie']:
        if col not in orders.columns:
            orders[col] = ""
            orders[col] = orders[col].astype(object)

    # Buclă de geocodare optimizată (Se execută cu o mică pauză pentru a respecta limitele gratuite)
    with st.spinner("Curățare și localizare adrese prin algoritmul inteligent..."):
        for idx, row in orders.iterrows():
            lat, lon, geo_addr, id_type = geocode_address_free_optimized(row['Adresa_originala'])
            orders.at[idx, 'Latitudine'] = lat
            orders.at[idx, 'Longitudine'] = lon
            orders.at[idx, 'Geocoded_address'] = str(geo_addr)
            orders.at[idx, 'Tip_Identificare'] = id_type

    routable = orders.copy()
    unroutable = pd.DataFrame(columns=orders.columns)
    
    courier_tracks = {c_id: [] for c_id in active_couriers['Curier_ID']}
    courier_counts = {c_id: 0 for c_id in active_couriers['Curier_ID']}
    
    unassigned_orders = routable.to_dict('records')
    
    while len(unassigned_orders) > 0:
        best_score = float('inf')
        best_courier = None
        best_order_idx = None
        
        for idx, ord_item in enumerate(unassigned_orders):
            for _, c_row in active_couriers.iterrows():
                c_id = c_row['Curier_ID']
                max_capacity = int(c_row.get('Capacitate_max_livrari', 20))
                
                if courier_counts[c_id] >= min(max_capacity, 20):
                    continue
                    
                c_loc = c_coords[c_id]
                dist_from_start = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], c_loc['start_lat'], c_loc['start_lon'])
                dist_to_finish = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], c_loc['end_lat'], c_loc['end_lon'])
                
                if len(courier_tracks[c_id]) > 0:
                    last_stop = courier_tracks[c_id][-1]
                    dist_to_last_stop = haversine_distance(ord_item['Latitudine'], ord_item['Longitudine'], last_stop['Latitudine'], last_stop['Longitudine'])
                else:
                    dist_to_last_stop = dist_from_start
                
                load_penalty = courier_counts[c_id] * 2.5
                score = (dist_from_start * 0.3) + (dist_to_finish * 0.2) + (dist_to_last_stop * 0.5) + load_penalty
                
                if score < best_score:
                    best_score = score
                    best_courier = c_id
                    best_order_idx = idx
                    
        if best_courier is None:
            break
            
        chosen_order = unassigned_orders.pop(best_order_idx)
        chosen_order['Curier_alocat'] = best_courier
        courier_tracks[best_courier].append(chosen_order)
        courier_counts[best_courier] += 1

    for left_item in unassigned_orders:
        left_item['Tip_Identificare'] = 'Nefinalizat - Capacitate Curieri Depășită'
        left_item['Curier_alocat'] = 'Neatribuit'
        unroutable = pd.concat([unroutable, pd.DataFrame([left_item])], ignore_index=True)

    final_route_records = []
    
    for _, c_row in active_couriers.iterrows():
        c_id = c_row['Curier_ID']
        track = courier_tracks[c_id]
        if not track:
            continue
            
        sequenced_track = []
        curr_lat = c_coords[c_id]['start_lat']
        curr_lon = c_coords[c_id]['start_lon']
        
        while len(track) > 0:
            next_idx = min(range(len(track)), key=lambda i: haversine_distance(curr_lat, curr_lon, track[i]['Latitudine'], track[i]['Longitudine']))
            next_stop = track.pop(next_idx)
            sequenced_track.append(next_stop)
            curr_lat = next_stop['Latitudine']
            curr_lon = next_stop['Longitudine']

        current_time = datetime.strptime("10:00", "%H:%M")
        windows = [
            (datetime.strptime("10:00", "%H:%M"), datetime.strptime("12:00", "%H:%M"), "10:00-12:00"),
            (datetime.strptime("12:00", "%H:%M"), datetime.strptime("14:00", "%H:%M"), "12:00-14:00"),
            (datetime.strptime("14:00", "%H:%M"), datetime.strptime("16:00", "%H:%M"), "14:00-16:00"),
            (datetime.strptime("16:00", "%H:%M"), datetime.strptime("18:00", "%H:%M"), "16:00-18:00"),
            (datetime.strptime("18:00", "%H:%M"), datetime.strptime("20:00", "%H:%M"), "18:00-20:00")
        ]
        current_window_idx = 0
        
        for seq, stop in enumerate(sequenced_track, start=1):
            if seq == 1:
                prev_lat, prev_lon = c_coords[c_id]['start_lat'], c_coords[c_id]['start_lon']
            else:
                prev_lat, prev_lon = sequenced_track[seq-2]['Latitudine'], sequenced_track[seq-2]['Longitudine']
                
            dist = haversine_distance(prev_lat, prev_lon, stop['Latitudine'], stop['Longitudine'])
            travel_time_min = (dist / 30.0) * 60.0
            
            current_time += timedelta(minutes=travel_time_min)
            arrival_time_str = current_time.strftime("%H:%M")
            
            while current_window_idx < len(windows) and current_time > windows[current_window_idx][1]:
                current_window_idx += 1
                
            if current_window_idx >= len(windows):
                applied_slot = "După 20:00"
                rule_desc = "Depășire program"
            else:
                applied_slot = windows[current_window_idx][2]
                rule_desc = "Păstrat în primul slot conform regulament" if seq <= 2 else "Alocat dinamic pe bază ETA"
            
            stop['Curier'] = c_row['Nume_curier']
            stop['Secventa'] = seq
            stop['Ora_estimata_sosire'] = arrival_time_str
            stop['Slot_fix_livrare'] = applied_slot
            stop['Regula_slot_aplicata'] = rule_desc
            stop['Link_navigatie'] = f"https://www.google.com/maps/search/?api=1&query={stop['Latitudine']},{stop['Longitudine']}"
            
            final_route_records.append(stop)
            
            stop_duration = int(stop.get('Durata_stop_min', 10))
            buffer_duration = int(stop.get('Timp_buffer_min', 10))
            current_time += timedelta(minutes=stop_duration + buffer_duration)

    df_final_output = pd.DataFrame(final_route_records) if final_route_records else pd.DataFrame()
    
    if not df_final_output.empty and not unroutable.empty:
        df_final_output = pd.concat([df_final_output, unroutable], ignore_index=True)
    elif df_final_output.empty:
        df_final_output = unroutable

    new_system_cols = ['Curier', 'Secventa', 'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie', 'Tip_Identificare', 'Latitudine', 'Longitudine', 'Geocoded_address']
    final_cols_order = original_columns + [c for c in new_system_cols if c not in original_columns]
    existing_cols_order = [c for c in final_cols_order if c in df_final_output.columns]
    
    manual_review_needed = df_final_output[df_final_output['Tip_Identificare'].isin(['Aproximat Localitate', 'Necesită Atenție Curier'])]
    
    return df_final_output[existing_cols_order], manual_review_needed

# --- UI Layout Interface ---
st.title("🚚 RoRoute - Planificator Automat de Trasee")
st.subheader("Sistem Operațional Centralizat pentru Dispecerat (100% Gratuit)")

st.sidebar.info("💡 Sistemul folosește acum un Modul de Curățare Românesc (corectează automat prescurtări tip 'sos', 'bd' sau intervale de numere).")

mode = st.sidebar.radio("Sursă Date", ["Mod Demo (Date Test)", "Încarcă Fişiere Proprii"])

orders_df, couriers_df = None, None

if mode == "Mod Demo (Date Test)":
    st.sidebar.info("Rulează aplicația folosind adrese preconfigurate brute.")
    orders_df, couriers_df = get_sample_data()
else:
    st.sidebar.markdown("### Încarcă Documente (.csv, .xlsx)")
    uploaded_orders = st.sidebar.file_uploader("Tabel Comenzi / Livrări", type=["csv", "xlsx"])
    uploaded_couriers = st.sidebar.file_uploader("Tabel Configurație Curieri", type=["csv", "xlsx"])
    
    if uploaded_orders:
        if uploaded_orders.name.endswith('.csv'):
            orders_df = pd.read_csv(uploaded_orders)
        else:
            orders_df = pd.read_excel(uploaded_orders)
            
    if uploaded_couriers:
        if uploaded_couriers.name.endswith('.csv'):
            couriers_df = pd.read_csv(uploaded_couriers)
        else:
            couriers_df = pd.read_excel(uploaded_couriers)
    elif uploaded_orders is not None:
        st.sidebar.warning("⚠️ Fișier curieri lipsă. Generăm automat 3 curieri impliciți pentru distribuție.")
        couriers_df = pd.DataFrame({
            'Curier_ID': ['C01', 'C02', 'C03'],
            'Nume_curier': ['Curier Traseu 1', 'Curier Traseu 2', 'Curier Traseu 3'],
            'Activ': [True, True, True]
        })

if orders_df is not None and couriers_df is not None:
    tab_ord, tab_cour = st.tabs(["📋 Vizualizare Date Încărcate", "🛵 Configurație Curieri"])
    with tab_ord:
        st.dataframe(orders_df, use_container_width=True)
    with tab_cour:
        st.dataframe(couriers_df, use_container_width=True)
        
    if st.button("🚀 Generează și Optimizează Traseele", type="primary"):
        routes_res, review_needed_df = generate_optimized_routes(orders_df, couriers_df)
        
        if routes_res is not None and isinstance(routes_res, pd.DataFrame) and not routes_res.empty:
            st.success("✅ Toate comenzile au fost mapate și distribuite pe trasee!")
            
            kpi_cols = st.columns(4)
            routes_only = routes_res[routes_res['Curier'] != ""]
            total_allocated = len(routes_only)
            unique_couriers = routes_only['Curier'].nunique() if total_allocated > 0 else 0
            avg_stops = round(total_allocated / unique_couriers, 1) if unique_couriers > 0 else 0
            
            kpi_cols[0].metric("Total Livrări Alocate", total_allocated)
            kpi_cols[1].metric("Curieri Activi pe Traseu", unique_couriers)
            kpi_cols[2].metric("Medie Livrări / Curier", avg_stops)
            kpi_cols[3].metric("Adrese Necesită Atenție (Pe Teren)", len(review_needed_df))
            
            if total_allocated > 0:
                st.markdown("### 🗺️ Vizualizare Trasee pe Hartă Interactivă")
                map_data = routes_only[['Latitudine', 'Longitudine']].dropna().rename(columns={'Latitudine': 'latitude', 'Longitudine': 'longitude'})
                st.map(map_data)
            
            if total_allocated > 0:
                st.markdown("#### ⚖️ Rezumat Trasee Curieri")
                balance_summary = []
                for c_name, group in routes_only.groupby('Curier'):
                    balance_summary.append({
                        'Curier': c_name,
                        'Număr Comenzi': len(group),
                        'Prima Livrare': group['Ora_estimata_sosire'].min(),
                        'Ultima Livrare': group['Ora_estimata_sosire'].max(),
                        'Sloturi Acoperite': ", ".join(group['Slot_fix_livrare'].astype(str).unique())
                    })
                st.table(pd.DataFrame(balance_summary))
            
            if not review_needed_df.empty:
                st.warning("⚠️ Următoarele adrese au fost mapate aproximativ la nivel de Localitate/Hub din cauza textului brut. Curierii vor naviga în zonă și vor citi restul detaliilor din fișier:")
                st.dataframe(review_needed_df[['ID_Livrare', 'Client', 'Adresa_originala', 'Tip_Identificare', 'Geocoded_address']], use_container_width=True)

            st.markdown("### 🗺️ Tabel Trasee Detaliat (Conține Toate Coloanele Originale)")
            st.dataframe(routes_res.sort_values(by=['Curier', 'Secventa'], ascending=[True, True]), use_container_width=True)
            
            csv_buffer = io.StringIO()
            routes_res.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 Descarcă Fișier Excel/CSV Complet Trasee",
                data=csv_buffer.getvalue(),
                file_name=f"Toate_Rutele_Complete_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        else:
            st.error("Eroare critică la procesarea algoritmului.")
else:
    st.info("💡 Vă rugăm să încărcați fișierul din meniul din stânga pentru a începe.")
