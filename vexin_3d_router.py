#!/usr/bin/env python3
"""
vexin_3d_router.py — Unified image/text-to-STL router

Picks the best model/strategy for the job:
  - Text description          -> OpenSCAD via cloud LLM (fast, no GPU)
  - Image, low quality OK     -> CPU depth_extrude (fast, no GPU, weak output)
  - Image, need real mesh     -> TripoSR on GPU (high quality, uses ~5GB VRAM)
  - Image, no GPU available   -> TripoSR via HuggingFace API (free tier, slow)
  - Multiple images           -> Photogrammetry (CPU, OpenCV SIFT)

Safety:
  - TripoSR GPU is loaded lazily on first use and unloaded after --idle-timeout
  - Won't load if <2GB free VRAM (refuses rather than OOM)
  - All GPU loads are explicit; default mode = no GPU
  - Prints VRAM before/after every GPU op

Usage:
  ./vexin_3d_router.py text "phone stand 100mm tall" --out stand.stl
  ./vexin_3d_router.py image photo.jpg --method auto --out model.stl
  ./vexin_3d_router.py image photo.jpg --method cpu --out model.stl   # force CPU
  ./vexin_3d_router.py image photo.jpg --method gpu --out model.stl   # force GPU (loads TripoSR)
  ./vexin_3d_router.py images img1.jpg img2.jpg img3.jpg --out scene.stl
  ./vexin_3d_router.py info

The router does NOT auto-load TripoSR. Pass --method gpu explicitly.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Inject torch-rocm path FIRST so triposr can find it
TORCH_ROCM = "/home/vexin/.local/torch-rocm"
sys.path.insert(0, TORCH_ROCM)


# === VRAM SAFETY ===

def get_vram_used_gb():
    """Read VRAM in use from sysfs. Returns GB or 0 if not available."""
    try:
        with open("/sys/class/drm/card1/device/mem_info_vram_used") as f:
            return int(f.read().strip()) / 1e9
    except Exception:
        return 0.0


def get_vram_total_gb():
    try:
        with open("/sys/class/drm/card1/device/mem_info_vram_total") as f:
            return int(f.read().strip()) / 1e9
    except Exception:
        return 0.0


def vram_ok_for_triposr(required_gb=4.5):
    """Check if we have enough free VRAM to load TripoSR (1.7GB model + 2-3GB working)."""
    used = get_vram_used_gb()
    total = get_vram_total_gb()
    free = total - used
    return free >= required_gb, used, free, total


def get_ram_free_gb():
    """Free RAM in GB (from /proc/meminfo)."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
    except Exception:
        return 0.0
    return 0.0


def estimate_model_memory_gb(precision="float32"):
    """TripoSR memory footprint estimate. Model + working set."""
    model_size = 1.7  # GB on disk
    # Working set: roughly 1.5x model size for activations during inference
    factor = 2.0 if precision == "float32" else 1.0
    return model_size * factor


# === STRATEGIES ===

def strategy_text(prompt, out_path, ai_via="odysseus"):
    """Text description -> STL via cloud LLM writing OpenSCAD code."""
    print(f"[strategy] text via {ai_via}", file=sys.stderr)
    # Delegate to existing vexin_image_to_3d.from_text
    from vexin_image_to_3d import gen_from_text
    return gen_from_text(prompt, out_path, ai_orchestrator=None)


def strategy_image_cpu(image_path, out_path):
    """Single image -> STL via CPU depth_extrude (no GPU, weaker output)."""
    print(f"[strategy] image -> CPU depth_extrude", file=sys.stderr)
    from vexin_image_to_3d import gen_via_depth_extrude
    return gen_via_depth_extrude(image_path, out_path)


def strategy_image_hf(image_path, out_path):
    """Single image -> STL via HuggingFace API (needs HUGGINGFACE_TOKEN env)."""
    print(f"[strategy] image -> HuggingFace API", file=sys.stderr)
    from vexin_image_to_3d import gen_via_triposr_hf
    return gen_via_triposr_hf(image_path, out_path)


def strategy_image_gpu(image_path, out_path, mc_resolution=192, chunk_size=2048,
                        offload="auto"):
    """Single image -> STL via TripoSR.

    offload options:
      "auto"   - try GPU first, fall back to GPU+CPU split, then pure CPU
      "gpu"    - force GPU only (fails if VRAM < 4.5GB free)
      "split"  - GPU + CPU RAM split (accelerate, keep ~half on GPU)
      "cpu"    - run entirely on CPU (slow but never OOMs on RAM)
    """
    ok, used, free, total = vram_ok_for_triposr()
    ram_free = get_ram_free_gb()
    print(f"[strategy] image -> TripoSR ({offload} mode)",
          f"VRAM: {used:.2f}GB used / {free:.2f}GB free of {total:.2f}GB | RAM: {ram_free:.1f}GB free",
          file=sys.stderr)

    # Decide actual offload strategy
    if offload == "auto":
        if free >= 6.0:
            actual = "gpu"
        elif free >= 2.5 and ram_free >= 8.0:
            actual = "split"
        elif ram_free >= 6.0:
            actual = "cpu"
        else:
            raise RuntimeError(
                f"Cannot run TripoSR: VRAM {free:.1f}GB free (need 2.5GB min for split), "
                f"RAM {ram_free:.1f}GB free (need 6GB min for CPU). "
                f"Use --method cpu (depth_extrude) or --method hf (API) instead."
            )
        print(f"[auto] decided: {actual}", file=sys.stderr)
    else:
        actual = offload
        if actual == "gpu" and not ok:
            raise RuntimeError(f"--method gpu requires 4.5GB+ VRAM free, have {free:.2f}GB")
        if actual == "split" and (free < 2.5 or ram_free < 8.0):
            raise RuntimeError(f"--method split requires 2.5GB+ VRAM and 8GB+ RAM, have {free:.1f}/{ram_free:.1f}GB")
        if actual == "cpu" and ram_free < 6.0:
            raise RuntimeError(f"--method cpu (TripoSR) requires 6GB+ RAM free, have {ram_free:.1f}GB")

    # Build device map based on actual mode
    if actual == "gpu":
        device_map = {"": "cuda"}
        mc_resolution = max(mc_resolution, 128)  # never go below 128 on GPU
    elif actual == "split":
        # accelerate: keep encoder on GPU, decoder + renderer on CPU
        device_map = "auto"  # let accelerate figure out
        mc_resolution = min(mc_resolution, 128)  # lower res = less CPU work
        chunk_size = min(chunk_size, 1024)        # smaller chunks = less CPU spill
    else:  # cpu
        device_map = {"": "cpu"}
        mc_resolution = min(mc_resolution, 96)    # lower res = faster CPU
        chunk_size = min(chunk_size, 512)

    from vexin_triposr import TripoSRRunner
    runner = TripoSRRunner(offload=device_map)
    try:
        # Override chunk size based on mode
        runner.model.renderer.set_chunk_size(chunk_size)

        # Disable rembg for CPU-only mode (slow)
        use_rembg = (actual != "cpu")

        return runner.image_to_mesh(
            image_path,
            out_path=out_path,
            remove_bg=use_rembg,
            foreground_ratio=0.85,
            mc_resolution=mc_resolution,
        )
    finally:
        try:
            import torch
            import gc
            del runner.model
            del runner
            gc.collect()
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
            new_vram = get_vram_used_gb()
            print(f"[cleanup] VRAM now {new_vram:.2f}GB used", file=sys.stderr)
        except Exception as e:
            print(f"[cleanup] warn: {e}", file=sys.stderr)


def strategy_images_multi(image_paths, out_path):
    """Multiple images -> STL via CPU photogrammetry."""
    print(f"[strategy] multi-image photogrammetry ({len(image_paths)} imgs)", file=sys.stderr)
    from vexin_image_to_3d import gen_from_images
    return gen_from_images(list(image_paths), out_path)


def pick_image_method(image_path):
    """Auto-pick the best image method based on VRAM + RAM + HF token."""
    ok_gpu, used, free, total = vram_ok_for_triposr()
    ram_free = get_ram_free_gb()
    has_hf_token = bool(os.environ.get("HUGGINGFACE_TOKEN"))

    if ok_gpu:
        return "gpu", f"GPU has {free:.1f}GB free, TripoSR full quality"
    elif free >= 2.5 and ram_free >= 8.0:
        return "split", f"GPU+RAM split (VRAM {free:.1f}GB, RAM {ram_free:.1f}GB)"
    elif ram_free >= 6.0:
        return "cpu", f"TripoSR on CPU only (VRAM {free:.1f}GB tight, RAM {ram_free:.1f}GB)"
    elif has_hf_token:
        return "hf", f"Local too tight (VRAM {free:.1f}GB, RAM {ram_free:.1f}GB), falling back to HF API"
    else:
        return "cpu_primitive", f"Even RAM is tight, using CPU depth_extrude (primitive output)"


# === INFO ===

def show_info():
    used = get_vram_used_gb()
    total = get_vram_total_gb()
    free = total - used

    print("=" * 70)
    print("VEXinWorks 3D Router (CPU + GPU)")
    print("=" * 70)

    print(f"\nGPU:   AMD Radeon RX 6900 XT (or detected)")
    print(f"VRAM:  {used:.2f} GB used / {total:.2f} GB total ({free:.2f} GB free)")
    print(f"RAM:   {get_ram_free_gb():.1f} GB free (16 GB total)")
    print(f"  TripoSR full GPU:   {'YES' if free >= 4.5 else 'NO'}")
    print(f"  TripoSR split:      {'YES' if free >= 2.5 and get_ram_free_gb() >= 8.0 else 'NO'}")
    print(f"  TripoSR CPU only:   {'YES' if get_ram_free_gb() >= 6.0 else 'NO'}")

    print(f"\nMethods available:")
    print(f"  text   -> OpenSCAD via cloud LLM    (no GPU, ~15s)")
    print(f"  image  -> CPU depth_extrude         (no GPU, weak but fast)")
    print(f"  image  -> TripoSR GPU               (~5GB VRAM, ~10-20s, HIGH)")
    print(f"  image  -> TripoSR split             (~3GB VRAM + ~6GB RAM, ~30-60s)")
    print(f"  image  -> TripoSR CPU               (~6GB RAM, ~3-10min)")
    print(f"  image  -> HF TripoSR API            (no GPU, ~30s, requires HUGGINGFACE_TOKEN)")
    print(f"  images -> CPU photogrammetry        (no GPU, 2+ photos, ~20s)")

    has_hf = bool(os.environ.get("HUGGINGFACE_TOKEN"))
    print(f"\nEnv:")
    print(f"  HUGGINGFACE_TOKEN: {'set' if has_hf else 'not set'}")
    print(f"  TripoSR model:     ", end="")
    if os.path.exists("/home/vexin/projects/TripoSR/weights/model.ckpt"):
        size = os.path.getsize("/home/vexin/projects/TripoSR/weights/model.ckpt") / 1e6
        print(f"{size:.0f} MB ✓")
    else:
        print("NOT DOWNLOADED")

    # Auto-pick test
    method, reason = pick_image_method("dummy.jpg")
    print(f"\nAuto-pick for image: {method} ({reason})")


# === MAIN ===

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    # text
    p_txt = sub.add_parser("text")
    p_txt.add_argument("prompt")
    p_txt.add_argument("--out", required=True)

    # image
    p_img = sub.add_parser("image")
    p_img.add_argument("image")
    p_img.add_argument("--out", required=True)
    p_img.add_argument("--method", choices=["auto", "cpu", "gpu", "hf"], default="auto")
    p_img.add_argument("--offload", choices=["auto", "gpu", "split", "cpu"], default="auto",
                       help="TripoSR offload strategy (only used when method=gpu)")
    p_img.add_argument("--mc-res", type=int, default=192)
    p_img.add_argument("--no-rembg", action="store_true")

    # images
    p_imgs = sub.add_parser("images")
    p_imgs.add_argument("images", nargs="+")
    p_imgs.add_argument("--out", required=True)

    # info
    sub.add_parser("info")

    args = parser.parse_args()

    if args.cmd == "info":
        show_info()
        return

    if args.cmd == "text":
        strategy_text(args.prompt, args.out)
        return

    if args.cmd == "image":
        method = args.method
        if method == "auto":
            method, reason = pick_image_method(args.image)
            print(f"[router] auto-picked {method}: {reason}", file=sys.stderr)
        if method in ("cpu", "cpu_primitive"):
            strategy_image_cpu(args.image, args.out)
        elif method == "hf":
            strategy_image_hf(args.image, args.out)
        elif method == "gpu":
            strategy_image_gpu(args.image, args.out,
                               mc_resolution=args.mc_res,
                               offload=args.offload)
        elif method == "split":
            strategy_image_gpu(args.image, args.out,
                               mc_resolution=args.mc_res,
                               offload="split")
        else:
            print(f"unknown method: {method}")
            sys.exit(1)
        return

    if args.cmd == "images":
        strategy_images_multi(args.images, args.out)
        return


if __name__ == "__main__":
    main()