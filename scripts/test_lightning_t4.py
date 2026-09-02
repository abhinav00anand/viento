import os

from lightning_sdk import Machine, Studio
from lightning_sdk.lightning_cloud.login import Auth

print("==> Configuring Lightning AI credentials...")
user_id = os.getenv("LIGHTNING_USER_ID", "<your-lightning-user-id>")
auth_token = os.getenv("LIGHTNING_AUTH_TOKEN", "<your-lightning-auth-token>")
auth = Auth()
auth.save(user_id=user_id, auth_token=auth_token)

print("==> Initializing Studio on teamspace 'financial-llm-training-project'...")
studio = Studio(
    name="viento-t4-node",
    teamspace="financial-llm-training-project",
    user="abhinav337463",
    create_ok=True,
)

print(f"Studio instance initialized: {studio.name}")
print(f"Current status: {studio.status}")

print("==> Starting Studio on Machine.T4...")
studio.start(machine=Machine.T4)

print(f"==> Studio started! Status: {studio.status}")
print("==> Running nvidia-smi on remote T4...")
out = studio.run("nvidia-smi")
print(out)
