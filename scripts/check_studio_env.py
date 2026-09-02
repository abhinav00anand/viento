from lightning_sdk.lightning_cloud.login import Auth
from lightning_sdk import Studio

auth = Auth()
auth.save(user_id="a3220a59-f43e-4d4d-843d-08b38bb8bbea", auth_token="sk-lit-698f2cfc-3fe8-433d-98da-b03aa08d5037")

studio = Studio(
    name="zephyr-t4-node",
    teamspace="financial-llm-training-project",
    user="abhinav337463"
)

cmd = "python3 -c 'import torch; print(\"CUDA available:\", torch.cuda.is_available()); print(\"Device:\", torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"None\"); print(\"Memory (GB):\", torch.cuda.get_device_properties(0).total_memory / 1e9 if torch.cuda.is_available() else 0)'"

print("==> Checking PyTorch CUDA on Studio...")
out = studio.run(cmd)
print(out)
