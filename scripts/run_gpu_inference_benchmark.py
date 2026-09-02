import base64
import sys
import time
from lightning_sdk.lightning_cloud.login import Auth
from lightning_sdk import Studio

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

print("==> Authenticating...")
auth = Auth()
auth.save(user_id="a3220a59-f43e-4d4d-843d-08b38bb8bbea", auth_token="sk-lit-698f2cfc-3fe8-433d-98da-b03aa08d5037")

studio = Studio(
    name="viento-t4-node",
    teamspace="financial-llm-training-project",
    user="abhinav337463"
)

with open("scripts/remote_viento_test.py", "rb") as f:
    b64_content = base64.b64encode(f.read()).decode("ascii")

# Model and dependencies are already cached and installed from the previous run!
remote_cmd = f"echo '{b64_content}' | base64 -d > run_viento_test.py && python3 run_viento_test.py"

print("==> Executing remote benchmark on T4 GPU...")
out = studio.run(remote_cmd)

with open("scripts/t4_test_output.txt", "w", encoding="utf-8") as f:
    f.write(out)
print("==> Saved output to scripts/t4_test_output.txt")

try:
    print(out)
except Exception:
    print(out.encode("ascii", errors="replace").decode("ascii"))
