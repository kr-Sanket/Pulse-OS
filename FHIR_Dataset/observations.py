import os
import json
from collections import Counter

folder = "fhir"

lab_counter = Counter()

for filename in os.listdir(folder):
    if not filename.endswith(".json"):
        continue

    with open(os.path.join(folder, filename), "r") as f:
        bundle = json.load(f)

    for entry in bundle.get("entry", []):

        resource = entry.get("resource", {})

        if resource.get("resourceType") == "Observation":

            code = resource.get("code", {})

            for coding in code.get("coding", []):

                display = coding.get("display")

                if display:
                    lab_counter[display] += 1

print("\nTop Observations\n")

for obs, count in lab_counter.most_common(50):
    print(f"{count:5}  {obs}")