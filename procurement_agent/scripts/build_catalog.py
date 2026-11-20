"""Writes the simulated manufacturing catalogue into data/quotes.json.

Supplier names are real; prices, stock and lead times are MOCKED for the demo,
and specs are simplified. Office products already in the file are kept.
Run:  .venv/bin/python scripts/build_catalog.py
"""
import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "quotes.json"
VALID = "2027-06-30"
SITES = {"DwyerOmega": "dwyeromega.com", "Siemens": "siemens.com", "WIKA": "wika.com",
         "Honeywell": "honeywell.com", "Emerson": "emerson.com"}


def item(supplier, ref, product, model, desc, price, breaks, lead, stock, stock_lead, moq, specs):
    return {
        "supplier": supplier, "supplier_site": SITES[supplier], "product": product, "model": model,
        "description": desc, "unit_price": price, "price_breaks": breaks, "currency": "USD",
        "lead_time_days": lead, "in_stock": stock, "stock_lead_days": stock_lead, "min_order_qty": moq,
        "valid_until": VALID, "quote_ref": ref, "specs": specs, "simulated": True,
    }


P = "pressure sensor"
pressure = [
    item("DwyerOmega", "DO-PX309-150", P, "PX309-150GI", "Pressure transducer, stainless steel, 4-20 mA",
         245.0, [[50, 229.0], [100, 215.0]], 12, 180, 3, 1,
         {"range_max": "150 psi", "output": "4-20 mA", "accuracy_pct": 0.25, "connection": '1/4" NPT',
          "ip_rating": "IP65", "temp_max": 85}),
    item("DwyerOmega", "DO-PX409-150", P, "PX409-150GI", "High-accuracy pressure transducer, 4-20 mA",
         595.0, [[50, 559.0], [100, 535.0]], 10, 40, 3, 1,
         {"range_max": "150 psi", "output": "4-20 mA", "accuracy_pct": 0.08, "connection": '1/4" NPT',
          "ip_rating": "IP67", "temp_max": 85}),
    item("DwyerOmega", "DO-626-100", P, "626-07-GH-P1-E1-S1", "Industrial pressure transmitter, 0-100 psi",
         212.0, [[100, 195.0]], 8, 300, 3, 1,
         {"range_max": "100 psi", "output": "4-20 mA", "accuracy_pct": 0.25, "connection": '1/4" NPT',
          "ip_rating": "IP66", "temp_max": 93}),
    item("Siemens", "SI-P220-16", P, "SITRANS P220 7MF1567-3DB00", "Pressure transmitter, 0-16 bar, 4-20 mA",
         365.0, [[50, 342.0], [100, 329.0]], 21, 0, 0, 10,
         {"range_max": "16 bar", "output": "4-20 mA", "accuracy_pct": 0.25, "connection": '1/4" NPT',
          "ip_rating": "IP67", "temp_max": 120}),
    item("Siemens", "SI-P200-10", P, "SITRANS P200 7MF1565-3CA00", "Pressure transmitter, 0-10 bar",
         298.0, [[100, 276.0]], 18, 0, 0, 10,
         {"range_max": "10 bar", "output": "4-20 mA", "accuracy_pct": 0.25, "connection": '1/4" NPT',
          "ip_rating": "IP65", "temp_max": 90}),
    item("Siemens", "SI-P320-HART", P, "SITRANS P320 7MF0300", "Smart pressure transmitter, HART",
         1480.0, [[50, 1395.0]], 28, 0, 0, 1,
         {"range_max": "250 psi", "output": "4-20 mA HART", "accuracy_pct": 0.065, "connection": '1/2" NPT',
          "ip_rating": "IP68", "temp_max": 125}),
    item("WIKA", "WI-A10-160", P, "A-10 (0-160 psi)", "General-purpose pressure transmitter",
         172.0, [[100, 158.0]], 14, 500, 4, 1,
         {"range_max": "160 psi", "output": "4-20 mA", "accuracy_pct": 0.5, "connection": '1/4" NPT',
          "ip_rating": "IP65", "temp_max": 80}),
    item("WIKA", "WI-S20-150", P, "S-20 (0-150 psi)", "Superior pressure transmitter, 0.25%",
         289.0, [[50, 272.0], [100, 259.0]], 16, 60, 4, 1,
         {"range_max": "150 psi", "output": "4-20 mA", "accuracy_pct": 0.25, "connection": '1/4" NPT',
          "ip_rating": "IP67", "temp_max": 85}),
    item("Honeywell", "HW-MLH150", P, "MLH150PGL01A", "Heavy-duty pressure sensor, ratiometric output",
         118.0, [[100, 104.0]], 9, 1200, 2, 1,
         {"range_max": "150 psi", "output": "0.5-4.5 V", "accuracy_pct": 0.25, "connection": '1/4" NPT',
          "ip_rating": "IP67", "temp_max": 125}),
    item("Honeywell", "HW-PX2-150C", P, "PX2AN1XX150PSCHX", "Heavy-duty pressure transducer, 4-20 mA",
         164.0, [[100, 149.0]], 20, 0, 0, 25,
         {"range_max": "150 psi", "output": "4-20 mA", "accuracy_pct": 0.25, "connection": '1/4" NPT',
          "ip_rating": "IP69K", "temp_max": 125}),
    item("Emerson", "EM-2051TG", P, "Rosemount 2051TG", "In-line gauge pressure transmitter, HART",
         1190.0, [[50, 1120.0]], 25, 0, 0, 1,
         {"range_max": "300 psi", "output": "4-20 mA HART", "accuracy_pct": 0.065, "connection": '1/2" NPT',
          "ip_rating": "IP66", "temp_max": 121}),
    item("Emerson", "EM-3051TG", P, "Rosemount 3051TG", "Premium in-line pressure transmitter, HART",
         1650.0, [], 30, 0, 0, 1,
         {"range_max": "150 psi", "output": "4-20 mA HART", "accuracy_pct": 0.04, "connection": '1/4" NPT',
          "ip_rating": "IP68", "temp_max": 121}),
]

T = "temperature sensor"
temperature = [
    item("DwyerOmega", "DO-PR21-6", T, "PR-21-2-100-1/4-6-E", "Pt100 RTD probe, class A, 1/4 NPT",
         74.0, [[50, 66.0]], 7, 400, 2, 1,
         {"sensor_type": "Pt100 RTD", "range_max": 260, "accuracy_class": "Class A", "connection": '1/4" NPT',
          "probe_length": "6 in"}),
    item("DwyerOmega", "DO-KQXL-6", T, "KQXL-14U-6", "Type K thermocouple probe",
         38.0, [[50, 33.0]], 5, 900, 2, 1,
         {"sensor_type": "Type K thermocouple", "range_max": 1100, "accuracy_class": "Standard",
          "connection": '1/4" NPT', "probe_length": "6 in"}),
    item("Siemens", "SI-TS500", T, "SITRANS TS500 7MC7500", "Pt100 RTD assembly with thermowell",
         218.0, [[50, 204.0]], 21, 0, 0, 5,
         {"sensor_type": "Pt100 RTD", "range_max": 600, "accuracy_class": "Class A", "connection": '1/2" NPT',
          "probe_length": "150 mm"}),
    item("WIKA", "WI-TR10", T, "TR10-C", "Pt100 RTD screw-in thermometer",
         142.0, [[50, 131.0]], 12, 120, 4, 1,
         {"sensor_type": "Pt100 RTD", "range_max": 250, "accuracy_class": "Class A", "connection": '1/4" NPT',
          "probe_length": "160 mm"}),
    item("Emerson", "EM-214C", T, "Rosemount 214C", "Pt100 RTD sensor, class A",
         265.0, [], 24, 0, 0, 1,
         {"sensor_type": "Pt100 RTD", "range_max": 450, "accuracy_class": "Class A", "connection": '1/2" NPT',
          "probe_length": "6 in"}),
]

F = "flow meter"
flow = [
    item("DwyerOmega", "DO-FMG91-2", F, "FMG91-PVDF-2", "Electromagnetic flow meter, 2 in",
         1460.0, [[5, 1390.0]], 14, 12, 4, 1,
         {"meter_type": "magnetic", "pipe_size": "2 in", "output": "4-20 mA", "accuracy_pct": 0.5,
          "ip_rating": "IP67"}),
    item("Siemens", "SI-MAG5100W-2", F, "SITRANS FM MAG 5100 W DN50", "Electromagnetic flow sensor with MAG 5000",
         2380.0, [[5, 2260.0]], 28, 0, 0, 1,
         {"meter_type": "magnetic", "pipe_size": "2 in", "output": "4-20 mA HART", "accuracy_pct": 0.4,
          "ip_rating": "IP67"}),
    item("Emerson", "EM-8705-2", F, "Rosemount 8705 (2 in)", "Magnetic flow meter sensor and transmitter",
         3150.0, [], 35, 0, 0, 1,
         {"meter_type": "magnetic", "pipe_size": "2 in", "output": "4-20 mA HART", "accuracy_pct": 0.25,
          "ip_rating": "IP68"}),
    item("Emerson", "EM-8800-2", F, "Rosemount 8800 Vortex (2 in)", "Vortex flow meter",
         2890.0, [], 32, 0, 0, 1,
         {"meter_type": "vortex", "pipe_size": "2 in", "output": "4-20 mA HART", "accuracy_pct": 0.65,
          "ip_rating": "IP66"}),
]

L = "level sensor"
level = [
    item("Siemens", "SI-LR100", L, "SITRANS LR100 7ML5432", "80 GHz radar level transmitter, 8 m",
         895.0, [[10, 845.0]], 20, 0, 0, 1,
         {"sensor_type": "radar", "range_max": "8 m", "output": "4-20 mA", "ip_rating": "IP68"}),
    item("Emerson", "EM-1208", L, "Rosemount 1208", "Non-contacting radar level and flow transmitter",
         1060.0, [], 22, 0, 0, 1,
         {"sensor_type": "radar", "range_max": "15 m", "output": "4-20 mA HART", "ip_rating": "IP68"}),
    item("DwyerOmega", "DO-ULS-6", L, "ULS-6 Ultrasonic", "Ultrasonic level transmitter, 6 m",
         468.0, [[10, 439.0]], 9, 25, 3, 1,
         {"sensor_type": "ultrasonic", "range_max": "6 m", "output": "4-20 mA", "ip_rating": "IP67"}),
    item("WIKA", "WI-LRT", L, "LRT-1 (radar)", "Radar level transmitter",
         990.0, [], 26, 0, 0, 1,
         {"sensor_type": "radar", "range_max": "30 m", "output": "4-20 mA HART", "ip_rating": "IP67"}),
]

X = "proximity sensor"
proximity = [
    item("Siemens", "SI-3RG4", X, "SIMATIC PXI 3RG4613", "Inductive proximity switch, M18, PNP",
         41.0, [[100, 36.5]], 10, 0, 0, 10,
         {"sensing_distance": "8 mm", "output": "PNP NO", "housing": "M18", "ip_rating": "IP67"}),
    item("Honeywell", "HW-922", X, "922FS8A-A4P-L", "Inductive proximity sensor, M18, PNP",
         44.0, [[100, 39.0]], 6, 800, 2, 1,
         {"sensing_distance": "8 mm", "output": "PNP NO", "housing": "M18", "ip_rating": "IP67"}),
    item("DwyerOmega", "DO-PRX18", X, "PRX-M18-8P", "Inductive proximity sensor, M18, PNP",
         29.5, [[100, 26.0]], 5, 1500, 2, 1,
         {"sensing_distance": "8 mm", "output": "PNP NO", "housing": "M18", "ip_rating": "IP67"}),
    item("Honeywell", "HW-922-NPN", X, "922FS5A-A4N-L", "Inductive proximity sensor, M12, NPN",
         36.0, [[100, 32.0]], 6, 600, 2, 1,
         {"sensing_distance": "4 mm", "output": "NPN NO", "housing": "M12", "ip_rating": "IP67"}),
]

existing = [r for r in json.loads(PATH.read_text()) if not r.get("simulated")]
rows = existing + pressure + temperature + flow + level + proximity
PATH.write_text(json.dumps(rows, indent=1) + "\n")
print(f"{len(existing)} office rows kept, {len(rows) - len(existing)} manufacturing rows written")
