# 🚚 Smart Routing System (București - Ilfov)

O aplicație web inteligentă dezvoltată în **Python** cu **Streamlit** pentru automatizarea, geocodarea strictă, balansarea pe timp și generarea foilor de parcurs (manifest) pentru curieri.

## ✨ Caracteristici Principale

1. **Gestionare & Validare Curieri:** Suport multiplu (culori unice per traseu), definire puncte de start/sosire și validare geografică strictă prin coordonate.
2. **Import Inteligent (Mapper):** Încărcare fișiere Excel/CSV (ex: WooCommerce) cu asociere dinamică a coloanelor pentru Adresă, Nume, Telefon și Ramburs.
3. **Filtrare Geografică B/IF:** Geocodare automată prin Nominatim API cu sistem de siguranță teritorială (*Bounding Box*) care izolează adresele din afara București / Ilfov.
4. **Algoritm de Balansare pe Timp:** Distribuție euristică bazată pe timpul acumulativ de condus (estimat prin OSRM API la ~35km/h în mediul urban) + un timp fix de 5 minute alocat per client.
5. **Hartă Interactivă Leaflet:** Afișarea rutelor reale și ferestre pop-up interactive cu detalii de livrare.
6. **Export Manifest:** Generare fișier Excel structurat pe tab-uri dedicate pentru fiecare curier, pregătit pentru teren.

---

## 🚀 Ghid de Instalare și Rulare Locală

### Prerechizite
Asigură-te că ai **Python 3.9+** instalat pe sistemul tău.

### 1. Clonarea repository-ului
```bash
git clone [https://github.com/utilizator/smart-routing-app.git](https://github.com/utilizator/smart-routing-app.git)
cd smart-routing-app
