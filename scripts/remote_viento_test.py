import time
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

print("=" * 65)
print("  ⚡ VIENTO DISTRIBUTED INFERENCE SYSTEM - CLOUD GPU TEST ⚡")
print("=" * 65)

# 1. GPU Telemetry
device_name = torch.cuda.get_device_name(0)
capability = torch.cuda.get_device_capability(0)
total_vram_mb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 2)

print(f"[*] CUDA Device Name      : {device_name}")
print(f"[*] CUDA Capability       : {capability}")
print(f"[*] Total VRAM            : {total_vram_mb:.1f} MB ({total_vram_mb / 1024:.2f} GB)")
print(f"[*] PyTorch Version       : {torch.__version__}")
print(f"[*] CUDA Compiled Version : {torch.version.cuda}")

# 2. Raw Tensor T4 FP16 Benchmark
print("\n[+] Running GPU T4 Tensor Core FP16 Matrix Multiplication (4096 x 4096)...")
size = 4096
a = torch.randn(size, size, device='cuda', dtype=torch.float16)
b = torch.randn(size, size, device='cuda', dtype=torch.float16)

# Warmup
for _ in range(10):
    c = torch.matmul(a, b)
torch.cuda.synchronize()

t0 = time.time()
iters = 50
for _ in range(iters):
    c = torch.matmul(a, b)
torch.cuda.synchronize()
dt = time.time() - t0
flops = 2 * (size ** 3) * iters / dt
tflops = flops / 1e12
print(f"[✓] T4 Matrix Multiplication: {dt / iters * 1000:.2f} ms/iter | Performance: {tflops:.2f} TFLOPS")

# 3. Load Small LLM (Qwen2.5-0.5B-Instruct) on T4 GPU
model_name = "Qwen/Qwen2.5-0.5B-Instruct"
print(f"\n[+] Loading small LLM '{model_name}' directly onto Tesla T4 (cuda:0)...")
t_load = time.time()
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    torch_dtype=torch.float16,
    device_map="cuda:0"
)
load_duration = time.time() - t_load
vram_used = torch.cuda.memory_allocated(0) / (1024 ** 2)
print(f"[✓] Model Loaded in {load_duration:.2f}s | VRAM Allocated: {vram_used:.1f} MB")

# 4. Generate Inference Prompt
prompt = "Explain in 3 short bullet points what Viento distributed edge inference mesh is and why it is useful."
messages = [
    {"role": "system", "content": "You are Viento AI, an intelligent agent running on the distributed inference mesh."},
    {"role": "user", "content": prompt}
]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
model_inputs = tokenizer([text], return_tensors="pt").to("cuda:0")

print(f"\n[+] Prompt: '{prompt}'")
print("[+] Generating response with Tesla T4 GPU...")

t_gen_start = time.time()
with torch.no_grad():
    generated_ids = model.generate(
        **model_inputs,
        max_new_tokens=150,
        do_sample=True,
        temperature=0.7
    )
torch.cuda.synchronize()
t_gen_end = time.time()

generated_ids = [
    output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
]
response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
new_tokens = len(generated_ids[0])
gen_time = t_gen_end - t_gen_start
tok_per_sec = new_tokens / gen_time

print(f"\n[+] Output Response:\n{response.strip()}")
print("\n" + "=" * 65)
print(f"[*] Tokens Generated      : {new_tokens}")
print(f"[*] Generation Time       : {gen_time:.3f} s")
print(f"[*] Inference Throughput  : {tok_per_sec:.2f} tokens/sec")
print(f"[*] Peak VRAM Allocated   : {torch.cuda.max_memory_allocated(0) / (1024 ** 2):.1f} MB")
print("=" * 65)
