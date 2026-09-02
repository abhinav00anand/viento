import os

from lightning_sdk import Studio
from lightning_sdk.lightning_cloud.login import Auth

user_id = os.getenv("LIGHTNING_USER_ID", "<your-lightning-user-id>")
auth_token = os.getenv("LIGHTNING_AUTH_TOKEN", "<your-lightning-auth-token>")
auth = Auth()
auth.save(user_id=user_id, auth_token=auth_token)

studio = Studio(
    name="viento-t4-node", teamspace="financial-llm-training-project", user="abhinav337463"
)

cmd = 'python3 -c \'import torch; print("CUDA available:", torch.cuda.is_available()); print("Device:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "None"); print("Memory (GB):", torch.cuda.get_device_properties(0).total_memory / 1e9 if torch.cuda.is_available() else 0)\''

print("==> Checking PyTorch CUDA on Studio...")
out = studio.run(cmd)
print(out)
