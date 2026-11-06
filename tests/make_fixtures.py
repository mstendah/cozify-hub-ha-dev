"""Build anonymised fixtures from a real /devices dump (run manually).

    python tests/make_fixtures.py devices.json
"""
import json
import sys

src = json.load(open(sys.argv[1]))
want = {
    "Ledvance (Coffee)": ("Desk lamp", "light_rgb"),
    "Iotsu T&H&CO2": ("Air quality sensor", "co2"),
    "Power (Coffee)": ("Coffee machine plug", "socket"),
    "Ovikello Etuovi": ("Doorbell", "doorbell"),
}
out = {}
for dev in src.values():
    if dev["name"] in want and want[dev["name"]][1] not in {v["_k"] for v in out.values()}:
        name, key = want[dev["name"]]
        d = json.loads(json.dumps(dev))
        d["id"] = f"00000000-0000-4000-8000-{len(out)+1:012d}"
        d["name"], d["_k"] = name, key
        d["room"] = ["10000000-0000-4000-8000-000000000001"]
        d.pop("bacnetIds", None)
        d["manufacturer"] = d.get("manufacturer")
        out[d["id"]] = d
json.dump(out, open("tests/fixtures/devices.json", "w"), indent=1)
print(len(out), "devices")
