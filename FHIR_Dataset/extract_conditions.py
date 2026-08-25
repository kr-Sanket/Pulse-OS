import os
import json
from collections import Counter

folder = "fhir"

disease_counter = Counter()

for filename in os.listdir(folder):
    if not filename.endswith(".json"):
        continue

    filepath = os.path.join(folder, filename)

    with open(filepath, "r") as f:
        bundle = json.load(f)

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})

        if resource.get("resourceType") == "Condition":

            code = resource.get("code", {})

            for coding in code.get("coding", []):

                disease = coding.get("display")

                if disease:
                    disease_counter[disease] += 1

print("\nTop Diseases\n")

for disease, count in disease_counter.most_common(50):
    print(f"{count:5}  {disease}")