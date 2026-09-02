import base64
import os
import sys

from lightning_sdk import Studio
from lightning_sdk.lightning_cloud.login import Auth

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

print("==> Authenticating...")
user_id = os.getenv("LIGHTNING_USER_ID", "<your-lightning-user-id>")
auth_token = os.getenv("LIGHTNING_AUTH_TOKEN", "<your-lightning-auth-token>")
auth = Auth()
auth.save(user_id=user_id, auth_token=auth_token)

studio = Studio(
    name="viento-t4-node", teamspace="financial-llm-training-project", user="abhinav337463"
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
