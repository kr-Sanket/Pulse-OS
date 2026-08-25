import os
import json
from collections import Counter

folder = "fhir"

procedure_counter = Counter()

for filename in os.listdir(folder):
    if not filename.endswith(".json"):
        continue

    with open(os.path.join(folder, filename), "r") as f:
        bundle = json.load(f)

    for entry in bundle.get("entry", []):

        resource = entry.get("resource", {})

        if resource.get("resourceType") == "Procedure":

            code = resource.get("code", {})

            for coding in code.get("coding", []):

                display = coding.get("display")

                if display:
                    procedure_counter[display] += 1

print("\nTop Procedures\n")

for procedure, count in procedure_counter.most_common(50):
    print(f"{count:5}  {procedure}")