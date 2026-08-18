import torch
import time
from src.models.ov_orthkd import OVOrthKDStudent

def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)

def measure_latency(model, device, input_shape=(1, 16, 3, 224, 224), audio_shape=(1, 16, 3, 224, 224), text_dim=1024):
    model.eval()
    model.to(device)

    # Dummy inputs
    frames = torch.randn(input_shape).to(device)
    specs = torch.randn(audio_shape).to(device)
    texts = torch.randn(1, text_dim).to(device)
    mask = torch.ones(1, 16).to(device)

    # Warmup
    for _ in range(10):
        with torch.no_grad():
            _ = model(frames, specs, texts, mask)

    # Measure
    start_time = time.time()
    iterations = 100
    for _ in range(iterations):
        with torch.no_grad():
            _ = model(frames, specs, texts, mask)

    end_time = time.time()
    avg_latency = (end_time - start_time) / iterations * 1000 # ms
    return avg_latency

if __name__ == "__main__":
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Standard Student Config
    model = OVOrthKDStudent(
        visual_backbone="convnextv2_tiny.fcmae_ft_in22k_in1k",
        audio_backbone="tf_efficientnetv2_b2.in1k",
        text_dim=1024,
        fusion_dim=384,
        temporal_layers=4,
        temporal_heads=8
    )

    params = count_parameters(model)
    print(f"Total Trainable Parameters: {params / 1e6:.2f} M")

    # Break down
    viz_params = count_parameters(model.visual_encoder)
    aud_params = count_parameters(model.audio_encoder)
    print(f"  Visual Backbone: {viz_params / 1e6:.2f} M")
    print(f"  Audio Backbone: {aud_params / 1e6:.2f} M")
    print(f"  Fusion + Heads: {(params - viz_params - aud_params) / 1e6:.2f} M")

    latency = measure_latency(model, device)
    print(f"Average Inference Latency (16 segments): {latency:.2f} ms")
    print(f"Throughput: {1000 / latency:.2f} clips/sec")
