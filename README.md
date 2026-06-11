# ⛽ Fuel Router API

A high-performance Django REST Framework backend designed to calculate optimal road trip routes across the US while simultaneously finding the cheapest fuel stops along the way to minimize total travel costs.

Built as an assessment project, this system leverages the free OSRM (Open Source Routing Machine) API for routing and Nominatim for geocoding, completely eliminating the need for paid, external API keys.

---

## 🚀 Features

* **Intelligent Route Planning:** Calculates the fastest driving route between any two US locations using OSRM.
* **Greedy Fuel Optimization:** Analyzes the route waypoints and your vehicle's maximum range (default 500 miles) to calculate exactly when and where you *must* stop for fuel.
* **Spatial Querying:** Utilizes a highly optimized, custom Django database query (Bounding-box pre-filtering + pure SQL Haversine math) to locate the absolutely cheapest fuel station within 10 miles of your required stop. No external API calls are made for fuel station lookups.
* **Performance Focused:** Aggressive 30-day caching for geocoding, 1-hour caching for exact route queries, and `db_index` optimization on all coordinate queries.
* **Total Cost Calculation:** Automatically calculates total miles, total gallons required, and total USD cost based on the exact real-world prices of the recommended stops.

---

## ⚙️ Environment Setup

### 1. Prerequisites
Ensure you have Python 3.10+ installed on your system.

### 2. Virtual Environment & Dependencies
Clone the repository and install the required packages:

```bash
# Create a virtual environment
python -m venv venv

# Activate the virtual environment
# Windows:
.\venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 3. Environment Variables
Copy the example environment file and configure it:

```bash
cp .env.example .env
```

Your `.env` should look like this:
```ini
SECRET_KEY=your-secret-key-here
DEBUG=True
```

### 4. Database Setup
Apply the Django migrations to create the SQLite database schema:
```bash
python manage.py migrate
```

---

## 📊 Loading Fuel Data

The project requires a dataset of fuel stations and retail prices. A CSV file (`fuel-prices-for-be-assessment.csv`) should be placed in the project root.

Run the custom management command to load this data rapidly using Django's `bulk_create`:

```bash
python manage.py load_fuel_prices fuel-prices-for-be-assessment.csv
```

> **⚠️ Geocoding Note:** The raw CSV data only provides addresses, not `latitude` and `longitude`. Because the `FuelOptimizer` relies on exact Haversine coordinate math, stations without coordinates will be ignored. To see actual fuel stops returned in the API, you must run a secondary geocoding pass (e.g., via a script hitting the Nominatim API) to populate the `FuelStation.latitude` and `FuelStation.longitude` fields in the database.

---

## 🌐 API Contract

Start the development server:
```bash
python manage.py runserver
```

### `POST /api/route/`

Calculates the optimal route and identifies the cheapest fuel stops.

**Headers:**
* `Content-Type: application/json`

**Request Body:**
```json
{
    "start": "Chicago, IL",
    "end": "Los Angeles, CA"
}
```

**Response (200 OK):**
```json
{
    "route_geometry": {
        "type": "LineString",
        "coordinates": [
            [-87.6244212, 41.8755616],
            [-87.62468, 41.87556],
            "... (thousands of coordinates representing the polyline)"
        ]
    },
    "fuel_stops": [
        {
            "station_name": "Pilot Travel Center",
            "address": "123 Highway 80",
            "city": "Omaha",
            "state": "NE",
            "price": 3.149,
            "latitude": 41.2586,
            "longitude": -95.9378
        }
    ],
    "total_miles": 2018.14,
    "total_gallons": 201.81,
    "total_fuel_cost_usd": 635.51
}
```

---

## 🧪 Testing

A Postman collection (`Fuel_Router_Postman_Collection.json`) is included in the repository root. Import this file directly into Postman to instantly test pre-configured route calculations (e.g., New York to Los Angeles, Chicago to Miami).
