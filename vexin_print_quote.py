#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vexin_print_quote.py — STL file analyzer (FIXED)

Estimates print time, material weight, and PLA cost in Paraguayan
guaraní (₲ / PYG) for a 3D print job. Reads both ASCII and binary STL.

Usage:
    python3 vexin_print_quote.py --stl_path model.stl
    python3 vexin_print_quote.py --stl_path model.stl --infill 20 --hours 4
"""

import argparse
import os
import struct
import sys
from dataclasses import dataclass


# Paraguay PLA pricing (₲ per kg) — adjust as needed
DEFAULT_PLA_PRICE_PER_KG = 35_000
DEFAULT_INFILL_PCT = 15
DEFAULT_PRINT_SPEED_MM_S = 60
DEFAULT_ELECTRICITY_COST_PER_KWH = 850  # ₲/kWh Paraguay 2026
DEFAULT_PRINTER_WATTS = 200  # average 3D printer wattage
DEFAULT_DENSITY_G_CM3 = 1.24  # PLA density
DEFAULT_DENSITY_PRINTED = 0.5  # printed parts ~50% solid (infill + walls)


@dataclass
class PrintQuote:
    volume_cm3: float
    bbox: tuple
    triangles: int
    weight_grams: float
    material_cost_pyg: float
    electricity_cost_pyg: float
    labor_cost_pyg: float
    total_cost_pyg: float
    estimated_hours: float
    suggested_price_pyg: float  # 3x cost
    material_used_kg: float

    def report(self) -> str:
        l, w, h = self.bbox
        return f"""
╔══════════════════════════════════════════════════════════════╗
║              VEXINWORKS 3D PRINT QUOTE                       ║
╠══════════════════════════════════════════════════════════════╣
║  📐 MODEL:                                                   ║
║    Bounding box:  {l:.1f} × {w:.1f} × {h:.1f} mm
║    Triangles:     {self.triangles:,}
║    Volume:        {self.volume_cm3:.2f} cm³
║                                                              ║
║  ⚖️  MATERIAL:                                                ║
║    Weight:        {self.weight_grams:.1f} g ({self.material_used_kg*1000:.0f} g needed)
║    PLA cost:      ₲{self.material_cost_pyg:>12,.0f}
║                                                              ║
║  ⚡ ELECTRICITY:                                              ║
║    Est. hours:    {self.estimated_hours:.1f} h
║    Electricity:   ₲{self.electricity_cost_pyg:>12,.0f}
║                                                              ║
║  👷 LABOR (₲30,000/h):                                        ║
║    Labor cost:    ₲{self.labor_cost_pyg:>12,.0f}
║                                                              ║
║  💰 TOTALS:                                                   ║
║    Production:    ₲{self.total_cost_pyg:>12,.0f}
║    Suggested price (3x): ₲{self.suggested_price_pyg:>8,.0f}
║                       ≈ USD {self.suggested_price_pyg/7300:>6.2f}
╚══════════════════════════════════════════════════════════════╝
"""


def parse_stl(stl_path: str):
    """Parse STL file, returns (triangles_list, bbox)."""
    with open(stl_path, 'rb') as f:
        data = f.read()

    # Detect format: binary STL starts with 80-byte header + uint32 triangle count
    is_binary = (
        len(data) > 84
        and not data[:5] == b'solid'  # 'solid' at start suggests ASCII
    )

    triangles = []
    min_v = [float('inf')] * 3
    max_v = [float('-inf')] * 3

    if is_binary:
        # Binary STL: skip 80-byte header, read uint32 triangle count
        tri_count = struct.unpack('<I', data[80:84])[0]
        offset = 84
        expected_size = 84 + tri_count * 50
        if expected_size > len(data):
            # Mismatch — fall back to ASCII
            is_binary = False
        else:
            for _ in range(tri_count):
                # 12 bytes normal (skip), 9*4=36 bytes vertices, 2 bytes attribute
                offset += 12  # skip normal
                v = list(struct.unpack('<9f', data[offset:offset+36]))
                offset += 36
                offset += 2  # skip attribute byte count
                # Reshape into 3 vertices
                verts = [(v[0], v[1], v[2]), (v[3], v[4], v[5]), (v[6], v[7], v[8])]
                triangles.append(verts)
                for vertex in verts:
                    for i in range(3):
                        if vertex[i] < min_v[i]:
                            min_v[i] = vertex[i]
                        if vertex[i] > max_v[i]:
                            max_v[i] = vertex[i]

    if not is_binary:
        # ASCII STL
        text = data.decode('utf-8', errors='ignore')
        current_face = []
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('vertex'):
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        v = (float(parts[1]), float(parts[2]), float(parts[3]))
                        current_face.append(v)
                        for i in range(3):
                            if v[i] < min_v[i]:
                                min_v[i] = v[i]
                            if v[i] > max_v[i]:
                                max_v[i] = v[i]
                    except (ValueError, IndexError):
                        continue
                if len(current_face) == 3:
                    triangles.append(current_face)
                    current_face = []

    bbox = (max_v[0] - min_v[0], max_v[1] - min_v[1], max_v[2] - min_v[2])
    return triangles, bbox


def triangle_volume(v0, v1, v2):
    """Signed volume of tetrahedron formed by triangle and origin."""
    return (
        v0[0] * (v1[1] * v2[2] - v1[2] * v2[1])
        + v0[1] * (v1[2] * v2[0] - v1[0] * v2[2])
        + v0[2] * (v1[0] * v2[1] - v1[1] * v2[0])
    ) / 6.0


def mesh_volume_cm3(triangles):
    """Compute total mesh volume in cm³ (assuming vertices in mm)."""
    if not triangles:
        return 0
    total = sum(triangle_volume(*tri) for tri in triangles)
    # mm³ to cm³: divide by 1000
    return abs(total) / 1000.0


def estimate_print_time_hours(volume_cm3, bbox, infill_pct, speed_mm_s):
    """Rough estimate: time depends on perimeter + infill + travel."""
    l, w, h = bbox
    # Estimate perimeter path length (mm)
    # Approximation: print 2 perimeters at 0.4mm width
    perimeter_layers = int(h / 0.2)  # 0.2mm layer height
    perimeter_per_layer = 2 * (l + w) * 2  # 4 perimeters around bbox
    total_perimeter = perimeter_per_layer * perimeter_layers
    perimeter_time = total_perimeter / (speed_mm_s * 3600)

    # Infill time
    infill_volume = volume_cm3 * (infill_pct / 100) * 0.9  # 90% efficiency
    infill_path_length = infill_volume * 100  # very rough: 100mm per cm³
    infill_time = infill_path_length / (speed_mm_s * 3600)

    # Travel + heatup overhead
    overhead = 0.25  # 15 min heatup/calibration

    return perimeter_time + infill_time + overhead


def calculate_quote(
    stl_path: str,
    infill_pct: float = DEFAULT_INFILL_PCT,
    pla_price_per_kg: float = DEFAULT_PLA_PRICE_PER_KG,
    hours: float = None,
) -> PrintQuote:
    """Generate a complete print quote for an STL file."""
    if not os.path.exists(stl_path):
        raise FileNotFoundError(f"STL file not found: {stl_path}")

    triangles, bbox = parse_stl(stl_path)
    if not triangles:
        raise ValueError(f"No triangles found in STL file. Is it valid?")
    volume_cm3 = mesh_volume_cm3(triangles)
    if volume_cm3 == 0:
        # Fallback: estimate from bounding box (50% solid)
        l, w, h = bbox
        volume_cm3 = (l * w * h / 1000) * DEFAULT_DENSITY_PRINTED

    # Weight with infill
    effective_density = DEFAULT_DENSITY_PRINTED * (1 - infill_pct/100) + (infill_pct/100)
    weight_grams = volume_cm3 * DEFAULT_DENSITY_G_CM3 * (infill_pct/100)  # ~infill weight
    # Add wall/shell weight (~20% of total volume)
    wall_weight = volume_cm3 * DEFAULT_DENSITY_G_CM3 * 0.20
    weight_grams = weight_grams + wall_weight
    weight_grams = max(weight_grams, 5.0)  # minimum 5g
    material_used_kg = weight_grams / 1000

    # Costs
    material_cost = material_used_kg * pla_price_per_kg
    if hours is None:
        hours = estimate_print_time_hours(
            volume_cm3, bbox, infill_pct, DEFAULT_PRINT_SPEED_MM_S
        )
    hours = hours or 0.5  # fallback to 30 min if estimation returns 0
    electricity_cost = (DEFAULT_PRINTER_WATTS / 1000) * hours * DEFAULT_ELECTRICITY_COST_PER_KWH
    labor_cost = hours * 30_000  # ₲30k/hour
    total_cost = material_cost + electricity_cost + labor_cost
    suggested_price = total_cost * 3  # 3x markup

    return PrintQuote(
        volume_cm3=volume_cm3,
        bbox=bbox,
        triangles=len(triangles),
        weight_grams=weight_grams,
        material_cost_pyg=material_cost,
        electricity_cost_pyg=electricity_cost,
        labor_cost_pyg=labor_cost,
        total_cost_pyg=total_cost,
        estimated_hours=hours,
        suggested_price_pyg=suggested_price,
        material_used_kg=material_used_kg,
    )


def main():
    parser = argparse.ArgumentParser(
        description="STL print quote calculator for Paraguay",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --stl_path model.stl
  %(prog)s --stl_path model.stl --infill 20
  %(prog)s --stl_path model.stl --hours 5
        """,
    )
    parser.add_argument("--stl_path", type=str, required=True, help="Path to STL file")
    parser.add_argument("--infill", type=float, default=DEFAULT_INFILL_PCT, help="Infill percentage (default: 15)")
    parser.add_argument("--pla_price", type=float, default=DEFAULT_PLA_PRICE_PER_KG, help="₲ per kg of PLA (default: 35000)")
    parser.add_argument("--hours", type=float, default=None, help="Override estimated print hours")

    args = parser.parse_args()

    try:
        quote = calculate_quote(
            args.stl_path,
            infill_pct=args.infill,
            pla_price_per_kg=args.pla_price,
            hours=args.hours,
        )
        print(quote.report())
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()