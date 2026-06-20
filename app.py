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

# --- Funcție de extragere BULLETPROOF pentru KML / KMZ ---
def parse_kml_flexible(uploaded_file):
    """
    Scanează flexibil un fișier KML sau KMZ (arhivă zip) exportat din Google My Maps.
    Dezarhivează automat dacă este KMZ și citește coordonatele + metadatele.
    """
    try:
        file_bytes = uploaded_file.read()
        
        # Pasul 1: Verificăm dacă este de fapt un fișier KMZ (arhivă zip)
        if zipfile.is_zipfile(io.BytesIO(file_bytes)):
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                # Căutăm fișierul doc.kml din interiorul arhivei KMZ
                kml_names = [name for name in z.namelist() if name.endswith('.kml')]
                if not kml_names:
                    return None, "Arhiva KMZ nu conține niciun fișier KML valid."
                utf8_content = z.read(kml_names[0]).decode('utf-8', errors='ignore')
        else:
            # Este un KML text normal
            utf8_content = file_bytes.decode('utf-8', errors='ignore')
            
        # Curățare namespace-uri XML pentru parsare mai ușoară
        clean_content = re.sub(r'\sxmlns="[^"]+"', '', utf8_content, count=1)
        try:
            root = ET.fromstring(clean_content.encode('utf-8'))
        except Exception:
            root = ET.fromstring(utf8_content.encode('utf-8', errors='ignore'))
            
        records = []
        
        # Iterăm prin toate elementele tip Placemark din structură
        for elem in root.iter():
            tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            
            if tag_name == 'Placemark':
                name_text = ""
                desc_text = ""
                coords_text = ""
                extended_data = {}
                
                for child in elem:
                    child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if child_tag == 'name' and child.text:
                        name_text = child.text.strip()
                    elif child_tag == 'description' and child.text:
                        desc_text = child.text.strip()
                    elif child_tag == 'ExtendedData':
                        for data_elem in child.iter():
                            d_tag = data_elem.tag.split('}')[-1] if '}' in data_elem.tag else data_elem.tag
                            if d_tag == 'Data':
                                data_name = data_elem.get('name')
                                value_elem = data_elem.find('.//value')
                                if data_name and value_elem is not None and value_elem.text:
                                    extended_data[data_name.strip()] = value_elem.text.strip()
                    elif child_tag == 'Point':
                        for point_child in child:
                            pt_tag = point_child.tag.split('}')[-1] if '}' in point_child.tag else point_child.tag
                            if pt_tag == 'coordinates' and point_child.text:
                                coords_text = point_child.text.strip()
                                
                if coords_text:
                    parts = coords_text.split(',')
                    if len(parts) >= 2:
                        try:
                            lon = float(parts[0].strip())
                            lat = float(parts[1].strip())
                            
                            rec = {
                                'KML_Name': name_text,
                                'Latitudine': lat,
                                'Longitudine': lon,
                                'Geocoded_address': name_text
                            }
                            # Atașăm metadatele extinse salvate de Google
                            for k, v in extended_data.items():
                                rec[f"KML_Ext_{k}"] = v
                                
                            records.append(rec)
                        except ValueError:
                            pass
                            
        if len(records) > 0:
            return pd.DataFrame(records), None
            
        # --- Fallback prin Căutare Text (Regex) directă în conținut ---
        records_regex = []
        placemarks_raw = re.findall(r'<Placemark>.*?</Placemark>', utf8_content, re.DOTALL)
        for pm in placemarks_raw:
            name_m = re.search(r'<name>(.*?)</name>', pm)
            coords_m = re.search(r'<coordinates>(.*?)</coordinates>', pm)
            name_t = name_m.group(1).strip() if name_m else "Fără Nume"
            
            phone_m = re.search(r'Phone \(Billing\):\s*([^\s<]+)', pm)
            first_m = re.search(r'First Name \(Shipping\):\s*([^\s<]+)', pm)
            last_m = re.search(r'Last Name \(Shipping\):\s*([^\s<]+)', pm)
            order_m = re.search(r'Nr\. Comanda:\s*([^\s<]+)', pm)
            
            if coords_m:
                c_parts = coords_m.group(1).strip().split(',')
                if len(c_parts) >= 2:
                    try:
                        rec = {
                            'KML_Name': name_t,
                            'Latitudine': float(c_parts[1].strip()),
                            'Longitudine': float(c_parts[0].strip()),
                            'Geocoded_address': name_t
                        }
                        if phone_m: rec['KML_Ext_Phone (Billing)'] = phone_m.group(1).strip()
                        if first_m: rec['KML_Ext_First Name (Shipping)'] = first_m.group(1).strip()
                        if last_m: rec['KML_Ext_Last Name (Shipping)'] = last_m.group(1).strip()
                        if order_m: rec['KML_Ext_Nr. Comanda'] = order_m.group(1).strip()
                        
                        records_regex.append(rec)
                    except ValueError:
                        pass
                        
        if len(records_regex) > 0:
            return pd.DataFrame(records_regex), None
            
        return None, "Nu s-au găsit puncte geografice. Verificați fișierul exportat din My Maps."
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
st.subheader("Potrivire avansată pe baza datelor extinse geografice")

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
        
        # Buclă inteligentă de potrivire
        for idx, row in orders_mapped.iterrows():
            match_found = False
            excel_phone = str(row['Telefon']).strip().replace('+', '') if row['Telefon'] else ""
            excel_first = str(row['Client_First']).strip().lower() if row['Client_First'] else ""
            excel_last = str(row['Client_Last']).strip().lower() if row['Client_Last'] else ""
            excel_id = str(row['ID_Livrare']).strip().lower() if row['ID_Livrare'] else ""
            
            for _, kml_row in kml_df.iterrows():
                kml_name = str(kml_row['KML_Name']).strip().lower()
                kml_phone = str(kml_row.get('KML_Ext_Phone (Billing)', '')).strip().replace('+', '')
                kml_first = str(kml_row.get('KML_Ext_First Name (Shipping)', '')).strip().lower()
                kml_last = str(kml_row.get('KML_Ext_Last Name (Shipping)', '')).strip().lower()
                kml_order = str(kml_row.get('KML_Ext_Nr. Comanda', '')).strip().lower()
                
                if excel_phone and kml_phone and (excel_phone in kml_phone or kml_phone in excel_phone):
                    match_found = True
                elif excel_id and kml_order and excel_id == kml_order:
                    match_found = True
                elif excel_first and excel_last and kml_first and kml_last and (excel_first in kml_first or excel_last in kml_last):
                    match_found = True
                elif len(kml_name) > 5 and kml_name in str(row['Adresa_originala']).lower():
                    match_found = True
                    
                if match_found:
                    orders_mapped.at[idx, 'Latitudine'] = kml_row['Latitudine']
                    orders_mapped.at[idx, 'Longitudine'] = kml_row['Longitudine']
                    break
                    
        orders_final_df = orders_mapped
        st.sidebar.success(f"📊 Date corelate cu succes!")

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
                st.warning("⚠️ Următoarele comenzi nu au fost găsite în fișierul de hărți:")
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
