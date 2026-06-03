import requests, json

url = "https://api.worldbank.org/v2/country/all/indicator/LP.LPI.OVRL.XQ?format=json&date=2018&per_page=300"
r = requests.get(url, timeout=15)
data = r.json()
records = {d["countryiso3code"]: d["value"] for d in data[1] if d["value"] is not None and len(d["countryiso3code"]) == 3}

with open("data/raw/lpi_2018.json", "w") as f:
    json.dump(records, f, indent=2)

print(f"Saved {len(records)} countries to lpi_2018.json")

our_isos = ["SGP","CHN","KOR","NLD","BEL","DEU","GBR","ESP","GRC","ITA","FRA","POL","ROU",
            "ARE","EGY","OMN","SAU","KEN","ZAF","MAR","YEM","IRN","PAK","USA","BRA","MEX",
            "COL","PAN","CAN","THA","MYS","IDN","TWN","JPN","PHL","VNM","LKA","IND"]
for iso in our_isos:
    print(f"  {iso}: {records.get(iso, 'N/A')}")
