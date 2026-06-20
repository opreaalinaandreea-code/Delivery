import streamlit as st
import pandas as pd
import numpy as np
import math
import xml.etree.ElementTree as ET
import re
import zipfile
from datetime import datetime, timedelta
import io

# --- Page Configuration ---
st.set_page_config(page_title="RoRoute - Planificator My Maps Excel", layout="wide")

# --- Funcție de extragere ULTRA-ROBUSTĂ pentru KML / KMZ ---
def parse_kml_flexible(uploaded_file):
    """
    Scanează complet fișierul KML sau KMZ folosind parsare XML dublată de Regex 
    pentru a garanta extragerea coordonatelor din Google My Maps.
    """
    try:
        file_bytes = uploaded_file.read()
        
        # Verificăm dacă este KMZ (arhivă zip)
        if zipfile.is_zipfile(io.BytesIO(file_bytes)):
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                kml_names = [name for name in z.namelist() if name.endswith('.kml')]
                if not kml_names:
                    return None, "Arhiva KMZ nu conține niciun fișier KML valid."
                utf8_content = z.read(kml_names[0]).decode('utf-8', errors='ignore')
        else:
            utf8_content = file_bytes.decode('utf-8', errors='ignore')
            
        records = []
        
        # --- METODA 1: Căutare directă prin Regex (Imună la erori de namespace sau structură XML) ---
        placemarks_raw = re.findall(r'<Placemark>.*?</Placemark>', utf8_content, re.DOTALL)
        
        for pm in placemarks_raw:
            name_m = re.search(r'<name>(.*?)</name>', pm)
            coords_m = re.search(r'<coordinates>(.*?)</coordinates>', pm)
            
            name_t = name_m.group(1).strip() if name_m else "Fără Nume"
            
            # Extragere metadate din ExtendedData sau descriere text brut
            phone_m = re.search(r'Phone \(Billing\):\s*([^\s<]+)', pm) or re.search(r'<Data name="Phone \(Billing\)">\s*<value>(.*?)</value>', pm, re.DOTALL)
            first_m = re.search(r'First Name \(Shipping\):\s*([^\s<]+)', pm) or re.search(r'<Data name="First Name \(Shipping\)">\s*<value>(.*?)</value>', pm, re.DOTALL)
            last_m = re.search(r'Last Name \(Shipping\):\s*([^\s<]+)', pm) or re.search(r'<Data name="Last Name \(Shipping\)">\s*<value>(.*?)</value>', pm, re.DOTALL)
            order_m = re.search(r'Nr\. Comanda:\s*([^\s<]+)', pm) or re.search(r'<Data name="Nr\. Comanda">\s*<value>(.*?)</value>', pm, re.DOTALL)
            
            if coords_m:
                # Curățăm caracterele de tip linie nouă sau spații din coordonate
                c_text = coords_m.group(1).strip()
                c_parts = c_text.split(',')
                if len(c_parts) >= 2:
                    try:
                        rec = {
                            'KML_Name': name_t,
                            'Latitudine': float(c_parts[1].strip()),
                            'Longitudine': float(c_parts[0].strip()),
                            'Geocoded_address': name_t
                        }
                        
                        # Curățăm tag-urile XML reziduale dacă meciul a fost din ExtendedData
                        clean_tag = lambda m: re.sub('<[^<]+?>', '', m.group(1)).strip() if m else ""
                        
                        rec['KML_Ext_Phone (Billing)'] = re.sub('<[^<]+?>', '', phone_m.group(1)).strip() if phone_m else ""
                        rec['KML_Ext_First Name (Shipping)'] = re.sub('<[^<]+?>', '', first_m.group(1)).strip() if first_m else ""
                        rec['KML_Ext_Last Name (Shipping)'] = re.sub('<[^<]+?>', '', last_m.group(1)).strip() if last_m else ""
                        rec['KML_Ext_Nr. Comanda'] = re.sub('<[^<]+?>', '', order_m.group(1)).strip() if order_m else ""
                        
                        records.append(rec)
                    except ValueError:
                        pass
                        
        if len(records) > 0:
            # Eliminăm eventualele duplicate citite eronat
            df_res = pd.DataFrame(records).drop_duplicates(subset=['Latitudine', 'Longitudine'])
            return df_res, None
            
        return None, "Nu s-au găsit puncte geografice în fișier. Verificați dacă harta conține pini plasați."
    except Exception as e:
        return None, f"Eroare la procesarea fișierului: {str(e)}"

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

# --- Standardizer / Column Mapper ---
def standardize_orders_df(df):
    df = df.copy()
    original_cols = list(df.columns)
    clean_cols = [str(c).strip() for c in df.columns]
    df.columns = clean_cols
    
    mapping = {
        'ID_Livrare': ['Nr. Comanda', 'ID_Livrare', 'Id', 'ID', 'Cod'],
        'Client_First': ['First Name (Shipping)', 'Nume', 'Client', 'Name'],
        'Client_Last': ['Last Name (Shipping)', 'Prenume'],
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
                
    return df, original_cols

# --- Core Routing Algorithm ---
def generate_optimized_routes(orders_df, original_columns):
    couriers_data = {
        'Curier_ID': ['C01', 'C02', 'C03'],
        'Nume_curier': ['Curier Principal 1', 'Curier Principal 2', 'Curier Principal 3'],
        'Capacitate_max_livrari': [20, 20, 20]
    }
    active_couriers = pd.DataFrame(couriers_data)

    c_coords = {
        'C01': {'start_lat': 44.4261, 'start_lon': 26.1024, 'end_lat': 44.4261, 'end_lon': 26.1024},
        'C02': {'start_lat': 44.4325, 'start_lon': 26.1001, 'end_lat': 44.4325, 'end_lon': 26.1001},
        'C03': {'start_lat': 44.4011, 'start_lon': 26.1189, 'end_lat': 44.4011, 'end_lon': 26.1189}
    }

    orders = orders_df.copy()
    for col in ['Curier', 'Secventa', 'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie', 'Status']:
        if col not in orders.columns:
            orders[col] = ""

    courier_tracks = {c_id: [] for c_id in active_couriers['Curier_ID']}
    courier_counts = {c_id: 0 for c_id in active_couriers['Curier_ID']}
    
    routable_items = orders[orders['Latitudine'].notna() & orders['Longitudine'].notna()].to_dict('records')
    unroutable = orders[orders['Latitudine'].isna() | orders['Longitudine'].isna()].copy()
    
    if len(routable_items) == 0:
        return orders, orders.copy()

    while len(routable_items) > 0:
        best_score = float('inf')
        best_courier = None
        best_order_idx = None
        
        for idx, ord_item in enumerate(routable_items):
            for _, c_row in active_couriers.iterrows():
                c_id = c_row['Curier_ID']
                max_capacity = int(c_row['Capacitate_max_livrari'])
                
                if courier_counts[c_id] >= max_capacity:
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
            
        chosen_order = routable_items.pop(best_order_idx)
        chosen_order['Curier_alocat'] = best_courier
        courier_tracks[best_courier].append(chosen_order)
        courier_counts[best_courier] += 1

    for left_item in routable_items:
        left_item['Status'] = 'Depășire Capacitate'
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
                
            applied_slot = windows[current_window_idx][2] if current_window_idx < len(windows) else "După 20:00"
            
            stop['Curier'] = c_row['Nume_curier']
            stop['Secventa'] = seq
            stop['Ora_estimata_sosire'] = arrival_time_str
            stop['Slot_fix_livrare'] = applied_slot
            stop['Regula_slot_aplicata'] = "Păstrat în primul slot" if seq <= 2 else "Alocat dinamic"
            stop['Link_navigatie'] = f"http://maps.google.com/?q={stop['Latitudine']},{stop['Longitudine']}"
            stop['Status'] = 'Optimizat Exact'
            
            final_route_records.append(stop)
            current_time += timedelta(minutes=20)

    df_routed = pd.DataFrame(final_route_records) if final_route_records else pd.DataFrame()
    
    if not df_routed.empty and not unroutable.empty:
        df_final_output = pd.concat([df_routed, unroutable], ignore_index=True)
    elif not df_routed.empty:
        df_final_output = df_routed
    else:
        df_final_output = unroutable

    new_system_cols = ['Curier', 'Secventa', 'Ora_estimata_sosire', 'Slot_fix_livrare', 'Regula_slot_aplicata', 'Link_navigatie', 'Status', 'Latitudine', 'Longitudine']
    final_cols_order = original_columns + [c for c in new_system_cols if c not in original_columns]
    existing_cols_order = [c for c in final_cols_order if c in df_final_output.columns]
    
    return df_final_output[existing_cols_order], unroutable

# --- UI Interface ---
st.title("🚚 RoRoute - Sincronizare Inteligentă Excel + My Maps")
st.subheader("Potrivire automată bazată pe Nume Client și Telefon")

st.sidebar.markdown("### 📋 Încărcare Date")
uploaded_excel = st.sidebar.file_uploader("1. Încarcă Tabelul Excel/CSV cu Comenzi", type=["csv", "xlsx"])
uploaded_kml = st.sidebar.file_uploader("2. Încarcă Harta (KML sau KMZ) din Google My Maps", type=["kml", "kmz"])

orders_final_df = None
original_columns_list = []

if uploaded_excel and uploaded_kml:
    if uploaded_excel.name.endswith('.csv'):
        df_raw = pd.read_csv(uploaded_excel)
    else:
        df_raw = pd.read_excel(uploaded_excel)
        
    orders_mapped, original_columns_list = standardize_orders_df(df_raw)
    kml_df, err = parse_kml_flexible(uploaded_kml)
    
    if err:
        st.error(err)
    else:
        orders_mapped['Latitudine'] = np.nan
        orders_mapped['Longitudine'] = np.nan
        
        # Buclă inteligentă de interconectare
        for idx, row in orders_mapped.iterrows():
            match_found = False
            excel_first = str(row['Client_First']).strip().lower() if row['Client_First'] else ""
            excel_last = str(row['Client_Last']).strip().lower() if row['Client_Last'] else ""
            excel_full_name = f"{excel_first} {excel_last}"
            
            # Curățăm numărul de telefon din Excel pentru a extrage ultimele 9 cifre (elimină 0 sau prefix de țară)
            ex_phone_clean = ''.join(filter(str.isdigit, str(row['Telefon'])))[-9:] if row['Telefon'] else ""
            
            for _, kml_row in kml_df.iterrows():
                kml_name = str(kml_row['KML_Name']).strip().lower()
                kml_first = str(kml_row.get('KML_Ext_First Name (Shipping)', '')).strip().lower()
                kml_last = str(kml_row.get('KML_Ext_Last Name (Shipping)', '')).strip().lower()
                kml_full_name = f"{kml_first} {kml_last}"
                
                # Curățăm numărul din KML
                kml_phone_raw = str(kml_row.get('KML_Ext_Phone (Billing)', ''))
                kml_phone_clean = ''.join(filter(str.isdigit, kml_phone_raw))[-9:] if kml_phone_raw else ""
                
                # Regula 1: Verificare număr telefon (Ultimele 9 cifre - Imun la +40 vs 07)
                if ex_phone_clean and kml_phone_clean and ex_phone_clean == kml_phone_clean:
                    match_found = True
                
                # Regula 2: Verificare Nume + Prenume complet
                if not match_found and excel_first and excel_last and kml_first and kml_last:
                    if (excel_first in kml_first and excel_last in kml_last) or (kml_full_name in excel_full_name or excel_full_name in kml_full_name):
                        match_found = True
                        
                if match_found:
                    orders_mapped.at[idx, 'Latitudine'] = kml_row['Latitudine']
                    orders_mapped.at[idx, 'Longitudine'] = kml_row['Longitudine']
                    break
                    
        orders_final_df = orders_mapped
        st.sidebar.success(f"📊 Date corelate cu succes pe baza metadatelor text!")

if orders_final_df is not None:
    st.info("✨ Sincronizarea a fost realizată. Coordonatele GPS au fost extrase direct din fișier.")
    
    if st.button("🚀 Generează Traseele Optimizate", type="primary"):
        routes_res, unrouted_df = generate_optimized_routes(orders_final_df, original_columns_list)
        
        if routes_res is not None and not routes_res.empty:
            st.success("✅ Traseele au fost calculate cu succes!")
            
            routes_only = routes_res[routes_res['Status'] == 'Optimizat Exact']
            total_allocated = len(routes_only)
            
            kpi_cols = st.columns(3)
            kpi_cols[0].metric("Total Comenzi Alocate", total_allocated)
            kpi_cols[1].metric("Curieri Pe Traseu", routes_only['Curier'].nunique() if total_allocated > 0 else 0)
            kpi_cols[2].metric("Comenzi Neidentificate în Hărți", len(routes_res) - total_allocated)
            
            if total_allocated > 0:
                st.markdown("### 🗺️ Vizualizare Trasee Curieri")
                map_data = routes_only[['Latitudine', 'Longitudine']].dropna().rename(columns={'Latitudine': 'latitude', 'Longitudine': 'longitude'})
                st.map(map_data)
                
                st.markdown("#### ⚖️ Timpi de Finalizare și Încărcare")
                balance_summary = []
                for c_name, group in routes_only.groupby('Curier'):
                    balance_summary.append({
                        'Curier': c_name,
                        'Număr Comenzi': len(group),
                        'Prima Livrare': group['Ora_estimata_sosire'].min(),
                        'Ultima Livrare (Ora Finish)': group['Ora_estimata_sosire'].max(),
                        'Sloturi': ", ".join(group['Slot_fix_livrare'].astype(str).unique())
                    })
                st.table(pd.DataFrame(balance_summary))
            
            unmatched_addresses = routes_res[routes_res['Status'] != 'Optimizat Exact']
            if not unmatched_addresses.empty:
                st.warning("⚠️ Următoarele comenzi din Excel nu au putut fi găsite în fișierul de hărți:")
                st.dataframe(unmatched_addresses[['ID_Livrare', 'Telefon', 'Adresa_originala']], use_container_width=True)

            st.markdown("### 🗺️ Tabel Trasee Finale (Conține toate coloanele originale)")
            st.dataframe(routes_res.sort_values(by=['Curier', 'Secventa']), use_container_width=True)
            
            csv_buffer = io.StringIO()
            routes_res.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 Descarcă Fișier Trasee Complet (Format CSV)",
                data=csv_buffer.getvalue(),
                file_name="Trasee_Complete_MyMaps.csv",
                mime="text/csv"
            )
else:
    st.info("💡 Încărcați simultan cele două fișiere în bara laterală pentru a porni maparea.")
