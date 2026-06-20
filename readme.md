# RoRoute - Automated Courier Route Planner

An operational, minimalist web application built with Python and Streamlit designed for scheduling and optimizing courier routes across Romania (primarily Bucharest and Ilfov areas).

## Features
- **Smart Geocoding Buffer**: Integrated automated Geocoding with fallback handlers for Romanian addresses powered by `geopy` and OpenStreetMap.
- **Dynamic Balancing Constraints**: Distributes orders among 1-4 couriers balancing finish times, geographical corridors, and a max limit of 20 packages per driver.
- **Fixed Delivery Slots**: Automatically assigns fixed 2-hour interval slots matching estimated times of arrival (ETA) with a built-in 10-minute operational buffer per stop.
- **Instant Export View**: Features quick execution dashboards and single-click CSV downloads for integration with navigation systems.

## Local Installation and Execution

1. Clone or download this project's code directory files.
2. Open your command terminal inside the project directory folder.
3. Install the required modules using `pip`:
   ```bash
   pip install -r requirements.txt