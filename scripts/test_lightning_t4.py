import os
import sys
import time
from lightning_sdk.lightning_cloud.login import Auth
from lightning_sdk import Studio, Machine, User, Teamspace

print("==> Configuring Lightning AI credentials...")
auth = Auth()
auth.save(user_id="a3220a59-f43e-4d4d-843d-08b38bb8bbea", auth_token="sk-lit-698f2cfc-3fe8-433d-98da-b03aa08d5037")

print("==> Initializing Studio on teamspace 'financial-llm-training-project'...")
studio = Studio(
    name="zephyr-t4-node",
    teamspace="financial-llm-training-project",
    user="abhinav337463",
    create_ok=True
)

print(f"Studio instance initialized: {studio.name}")
print(f"Current status: {studio.status}")

print("==> Starting Studio on Machine.T4...")
studio.start(machine=Machine.T4)

print(f"==> Studio started! Status: {studio.status}")
print("==> Running nvidia-smi on remote T4...")
out = studio.run("nvidia-smi")
print(out)
