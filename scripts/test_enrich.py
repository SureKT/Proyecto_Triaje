#!/usr/bin/env python3
"""Prueba local de POST /enriquecer/ (ejecutar desde la raíz del proyecto)."""
import json
import sys
import urllib.request
from pathlib import Path

API = "http://localhost:8002/enriquecer/"
GUID = sys.argv[1] if len(sys.argv) > 1 else "test-res0001"
TXT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("text/RES0001.txt")

texto = TXT.read_text(encoding="utf-8", errors="replace")
body = json.dumps({"guid": GUID, "texto": texto}).encode("utf-8")
req = urllib.request.Request(
    API,
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=300) as resp:
    print(json.dumps(json.load(resp), indent=2, ensure_ascii=False))
