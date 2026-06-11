"""Patch GGUF context_length metadata to enable OCR with larger context."""
import struct, sys, shutil, os

GGUF_PATH = r"D:\deepseek\data\qwen2-vl-gguf\Qwen2-VL-2B-Instruct-Q4_K_M.gguf"
BACKUP_PATH = GGUF_PATH + ".bak"
NEW_CTX = 2048

# Read GGUF header
with open(GGUF_PATH, "rb") as f:
    header = f.read(4)
    assert header == b"GGUF", f"Not GGUF: {header}"
    version = struct.unpack("<I", f.read(4))[0]
    n_tensors = struct.unpack("<Q", f.read(8))[0]
    n_kv = struct.unpack("<Q", f.read(8))[0]
    print(f"GGUF v{version}, {n_tensors} tensors, {n_kv} keys")

    # Read all metadata to find context_length and offset
    metadata_start = f.tell()
    kv_offsets = {}
    kv_values = {}

    for i in range(n_kv):
        key_start = f.tell()
        kl = struct.unpack("<Q", f.read(8))[0]
        key = f.read(kl).decode("utf-8", errors="replace")
        vt = struct.unpack("<I", f.read(4))[0]
        val_start = f.tell()

        if vt == 0:   # uint8
            val = struct.unpack("<B", f.read(1))[0]
        elif vt == 1: # int8
            val = struct.unpack("<b", f.read(1))[0]
        elif vt == 2: # uint16
            val = struct.unpack("<H", f.read(2))[0]
        elif vt == 3: # int16
            val = struct.unpack("<h", f.read(2))[0]
        elif vt == 4: # uint32
            val = struct.unpack("<I", f.read(4))[0]
        elif vt == 5: # int32
            val = struct.unpack("<i", f.read(4))[0]
        elif vt == 6: # float32
            val = struct.unpack("<f", f.read(4))[0]
        elif vt == 7: # bool
            val = struct.unpack("<?", f.read(1))[0]
        elif vt == 8: # string
            slen = struct.unpack("<Q", f.read(8))[0]
            val = f.read(slen).decode("utf-8", errors="replace")
        elif vt == 10: # uint64
            val = struct.unpack("<Q", f.read(8))[0]
        elif vt == 11: # int64
            val = struct.unpack("<q", f.read(8))[0]
        elif vt == 12: # float64
            val = struct.unpack("<d", f.read(8))[0]
        else:
            # Complex type, skip
            if vt == 9:  # array
                atype = struct.unpack("<I", f.read(4))[0]
                alen = struct.unpack("<Q", f.read(8))[0]
                elem_sizes = {0:1,1:1,2:2,3:2,4:4,5:4,6:4,7:1,8:8,9:8,10:8,11:8,12:8}
                f.read(alen * elem_sizes.get(atype, 8))
            val = f"<type {vt}>"

        kv_offsets[key] = (val_start, vt)
        kv_values[key] = val

        if "context" in key.lower() or "rope" in key.lower():
            try:
                print(f"  [{vt}] {key} = {val}")
            except (UnicodeEncodeError, UnicodeDecodeError):
                print(f"  [{vt}] {key} = <binary>")

print(f"\nLooking for context_length key...")
ctx_key = None
for key in kv_values:
    if "context_length" in key.lower() or key.endswith(".context_length"):
        ctx_key = key
        break

if not ctx_key:
    print("No context_length key found! Available keys:")
    for key in sorted(kv_values.keys()):
        print(f"  {key} = {kv_values[key]}")
    sys.exit(1)

old_ctx = kv_values[ctx_key]
print(f"\nFound: {ctx_key} = {old_ctx}")
print(f"Will change to: {NEW_CTX}")

# Backup
if not os.path.exists(BACKUP_PATH):
    shutil.copy2(GGUF_PATH, BACKUP_PATH)
    print(f"Backup created: {BACKUP_PATH}")
else:
    print(f"Backup already exists: {BACKUP_PATH}")

# Read the value type
val_offset, val_type = kv_offsets[ctx_key]
print(f"Value at offset {val_offset}, type {val_type}")

# Write new value
type_to_fmt = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 10: "<Q", 11: "<q"}
type_to_size = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 10: 8, 11: 8}

if val_type not in type_to_fmt:
    print(f"Cannot patch type {val_type} - unsupported")
    sys.exit(1)

fmt = type_to_fmt[val_type]
size = type_to_size[val_type]
packed = struct.pack(fmt, NEW_CTX)

with open(GGUF_PATH, "r+b") as f:
    f.seek(val_offset)
    f.write(packed)

print(f"Patched! Wrote {NEW_CTX} ({packed.hex()}) at offset {val_offset}")
print(f"Verify by running: docker restart qwen2vl")
