import torch

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

if torch.cuda.is_available():
    gpu_name = torch.cuda.get_device_name(0)
    print(f"{GREEN}SUCCESS: CUDA is available. Detected GPU: {gpu_name}{RESET}")
else:
    print(f"{RED}ERROR: CUDA was not detected. GPU acceleration will fail.{RESET}")
