import os
import json
from collections import Counter

folder = "fhir"

medicine_counter = Counter()

for filename in os.listdir(folder):
    if not filename.endswith(".json"):
        continue

    with open(os.path.join(folder, filename), "r") as f:
        bundle = json.load(f)

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        if resource.get("resourceType") == "MedicationRequest":

            medication = resource.get("medicationCodeableConcept", {})

            for coding in medication.get("coding", []):

                name = coding.get("display")

                if name:
                    medicine_counter[name] += 1

print("\nTop Medicines\n")

for name, count in medicine_counter.most_common(50):
    print(f"{count:5}  {name}")