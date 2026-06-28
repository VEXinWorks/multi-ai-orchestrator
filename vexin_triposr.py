#!/usr/bin/env python3
"""
vexin_triposr.py — Self-hosted TripoSR image-to-3D pipeline

Uses TripoSR (stabilityai/TripoSR) running on local AMD GPU via ROCm.
No API calls, no external services. Just GPU.

Usage:
  ./vexin_triposr.py image photo.jpg --out model.stl
  ./vexin_triposr.py info

Requirements:
  - PyTorch with ROCm at /home/vexin/.local/torch-rocm
  - TripoSR model at /home/vexin/projects/TripoSR/weights/model.ckpt
  - Trimesh, OpenSCAD
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Inject our torch install first
sys.path.insert(0, "/home/vexin/.local/torch-rocm")

import torch
import numpy as np
from PIL import Image
import trimesh

# TripoSR imports
sys.path.insert(0, "/home/vexin/projects/TripoSR")
from tsr.system import TSR
from tsr.utils import remove_background, resize_foreground, save_video


TRIPOSR_MODEL = "/home/vexin/projects/TripoSR/weights/model.ckpt"
TRIPOSR_DIR = "/home/vexin/projects/TripoSR/weights"  # contains both config.yaml and model.ckpt
TRIPOSR_REPO = "/home/vexin/projects/TripoSR"
DEFAULT_OUT = "/tmp/triposr_output.stl"


class TripoSRRunner:
    def __init__(self, model_path=TRIPOSR_MODEL, device=None, offload=None):
        """device: "cuda" | "cpu" | None (auto)
        offload: dict for device_map (e.g., {"": "cuda"}), or "auto" for accelerate.
                 If provided, takes precedence over device."""
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[init] target={self.device} offload={offload}", file=sys.stderr)

        if not torch.cuda.is_available() and self.device == "cuda":
            print("[!] no CUDA/ROCm available — falling back to CPU (slow)", file=sys.stderr)
            self.device = "cpu"

        print(f"[init] loading TripoSR model from {TRIPOSR_DIR}...", file=sys.stderr)
        t0 = time.time()
        self.model = TSR.from_pretrained(
            TRIPOSR_DIR,
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
        self.model.renderer.set_chunk_size(8192)

        # Apply device/offload
        if offload == "auto":
            # Use accelerate to auto-split between GPU and CPU RAM
            try:
                from accelerate import dispatch_model, infer_auto_device_map
                max_mem = {0: "3GiB", "cpu": "10GiB"}
                device_map = infer_auto_device_map(self.model, max_memory=max_mem)
                self.model = dispatch_model(self.model, device_map=device_map)
                print(f"[init] accelerate dispatched across GPU+CPU", file=sys.stderr)
            except ImportError:
                print("[!] accelerate not installed — using plain CPU", file=sys.stderr)
                self.model.to("cpu")
        elif isinstance(offload, dict):
            # Explicit device map (e.g., {"": "cpu"} or {"": "cuda"})
            target = offload.get("", "cuda")
            self.model.to(target)
            print(f"[init] moved to {target}", file=sys.stderr)
        else:
            self.model.to(self.device)

        print(f"[init] model loaded in {time.time()-t0:.1f}s", file=sys.stderr)

    def image_to_mesh(self, image_path, out_path=DEFAULT_OUT,
                      remove_bg=True, foreground_ratio=0.85,
                      mc_resolution=256, formats=("mesh",)):
        """Convert an image to a 3D mesh.

        Args:
            image_path: input image
            out_path: where to save (.stl, .obj, .glb)
            remove_bg: use rembg to remove background
            foreground_ratio: how much of the image the object should fill
            mc_resolution: marching cubes resolution (higher = more detail, more VRAM)
            formats: which TripoSR outputs to keep ("mesh", "video")
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(image_path)

        print(f"[load] {image_path}", file=sys.stderr)
        image = Image.open(image_path).convert("RGBA")

        if remove_bg:
            print("[preprocess] removing background (rembg)...", file=sys.stderr)
            image = remove_background(image)
            # rembg may add alpha or not — ensure RGBA for resize_foreground
            if image.mode != "RGBA":
                image = image.convert("RGBA")
        else:
            # No rembg: synthesize a fake alpha (everything is foreground)
            # so resize_foreground works the same way
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            # Fill alpha = 255 (fully opaque) — keeps everything
            from PIL import Image as PILImage
            r, g, b, a = image.split()
            a = PILImage.new("L", image.size, 255)
            image = PILImage.merge("RGBA", (r, g, b, a))

        print(f"[preprocess] resize foreground (ratio={foreground_ratio})", file=sys.stderr)
        image = resize_foreground(image, foreground_ratio)

        # TripoSR image tokenizer expects RGB
        image = image.convert("RGB")

        print(f"[infer] running TripoSR (mc_resolution={mc_resolution})", file=sys.stderr)
        t0 = time.time()
        with torch.no_grad():
            scene_codes = self.model([image], device=self.device)
        print(f"[infer] done in {time.time()-t0:.1f}s", file=sys.stderr)

        print("[extract] extracting meshes via marching cubes", file=sys.stderr)
        t0 = time.time()
        meshes = self.model.extract_mesh(scene_codes, has_vertex_color=False,
                                          resolution=mc_resolution)
        print(f"[extract] {len(meshes)} mesh(es) in {time.time()-t0:.1f}s", file=sys.stderr)

        # TripoSR returns a list of trimesh.Trimesh, one per scene
        for i, mesh in enumerate(meshes):
            if i == 0:
                target = out_path
            else:
                base, ext = os.path.splitext(out_path)
                target = f"{base}_{i}{ext}"

            # trimesh.Trimesh or list of meshes
            if isinstance(mesh, list):
                mesh = trimesh.util.concatenate(mesh)

            print(f"[save] {target} ({len(mesh.vertices)} verts, {len(mesh.faces)} faces, "
                  f"watertight={mesh.is_watertight})", file=sys.stderr)

            ext = os.path.splitext(target)[1].lower()
            if ext == ".stl":
                mesh.export(target)
            elif ext == ".obj":
                mesh.export(target)
            elif ext in (".glb", ".gltf"):
                mesh.export(target)
            else:
                # default STL
                mesh.export(target + ".stl")

            # Print stats
            print(f"[stats] bounds={mesh.bounds.tolist()}, volume={mesh.volume:.1f} mm³", file=sys.stderr)

        return out_path


def show_info():
    print("=" * 60)
    print("VEXinWorks TripoSR (self-hosted image-to-3D)")
    print("=" * 60)
    print(f"\nPyTorch:        {torch.__version__}")
    print(f"ROCm/CUDA:      {torch.version.hip or 'no'}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU:            {torch.cuda.get_device_name(0)}")
        print(f"VRAM:           {round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2)} GB")

    print(f"\nTripoSR repo:   {TRIPOSR_REPO}")
    print(f"TripoSR model:  {TRIPOSR_MODEL}")
    if os.path.exists(TRIPOSR_MODEL):
        size = os.path.getsize(TRIPOSR_MODEL) / 1e6
        print(f"  size:         {size:.1f} MB ✓")
    else:
        print(f"  ✗ NOT FOUND — run: python3 -c \"from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='stabilityai/TripoSR', filename='model.ckpt', local_dir='{TRIPOSR_REPO}/weights/')\"")

    # Bench (if model available)
    if os.path.exists(TRIPOSR_MODEL):
        print("\nLoading model for a quick benchmark...")
        try:
            runner = TripoSRRunner()
            print(f"\nReady! Estimated time per image: ~30s on GPU, ~5-10min on CPU")
        except Exception as e:
            print(f"\n[!] Could not load model: {e}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    p_img = sub.add_parser("image", help="image to 3D mesh")
    p_img.add_argument("image")
    p_img.add_argument("--out", default=DEFAULT_OUT)
    p_img.add_argument("--no-rembg", action="store_true",
                       help="skip background removal")
    p_img.add_argument("--fg-ratio", type=float, default=0.85)
    p_img.add_argument("--mc-res", type=int, default=256,
                       help="marching cubes resolution (64-512, default 256)")

    sub.add_parser("info", help="show GPU + model status")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    if args.cmd == "info":
        show_info()
    elif args.cmd == "image":
        runner = TripoSRRunner()
        out = runner.image_to_mesh(
            args.image,
            out_path=args.out,
            remove_bg=not args.no_rembg,
            foreground_ratio=args.fg_ratio,
            mc_resolution=args.mc_res,
        )
        print(f"\n✓ done: {out}")


if __name__ == "__main__":
    main()