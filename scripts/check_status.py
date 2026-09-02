import os

import requests

auth_token = os.getenv("LIGHTNING_AUTH_TOKEN", "<your-lightning-auth-token>")
project_id = os.getenv("LIGHTNING_PROJECT_ID", "<your-lightning-project-id>")
headers = {"Authorization": f"Bearer {auth_token}"}
r = requests.get(f"https://lightning.ai/v1/projects/{project_id}/cloudspaces", headers=headers)
data = r.json()
cloudspaces = data.get("cloudspaces", [])
print(f"Number of cloudspaces: {len(cloudspaces)}")
for cs in cloudspaces:
    name = cs.get("name")
    phase = cs.get("status", {}).get("phase")
    spec = cs.get("spec", {}).get("instanceType")
    print(f"Name: {name} | Phase: {phase} | Machine: {spec}")
