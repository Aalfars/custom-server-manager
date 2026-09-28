import os
import shutil
import subprocess
from typing import Optional, Dict, List

BINARY_EXTENSIONS = {
    ".gz", ".tar", ".tgz", ".bz2", ".tbz2", ".xz", ".txz", ".zip", ".rar", ".7z",
    ".ex5", ".ex4", ".exe", ".bin", ".so", ".dll", ".iso", ".img", ".deb", ".rpm",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svgz", ".bmp", ".tiff",
    ".pdf", ".docx", ".xlsx", ".pptx", ".mp4", ".mp3", ".wav", ".avi", ".mkv",
    ".pyc", ".db", ".sqlite", ".sqlite3", ".o", ".a"
}

def is_binary_file(filepath: str) -> bool:
    lower_path = filepath.lower()
    _, ext = os.path.splitext(lower_path)
    if ext in BINARY_EXTENSIONS:
        return True
    if lower_path.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        return True
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(8192)
            if b"\x00" in chunk:
                return True
    except Exception:
        pass
    return False

def list_directory(path: str = "/root", limit: int = 200) -> Dict:
    target = os.path.abspath(path)
    if not os.path.exists(target):
        raise FileNotFoundError("Path not found")
    if not os.path.isdir(target):
        raise NotADirectoryError("Target path is not a directory")

    entries = []
    with os.scandir(target) as it:
        for entry in it:
            try:
                st = entry.stat()
                entries.append({
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": entry.is_dir(),
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "mode": oct(st.st_mode)[-3:]
                })
            except Exception:
                continue

    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return {
        "current_path": target,
        "entries": entries[:limit]
    }

def read_file(path: str, max_size: int = 2 * 1024 * 1024) -> Dict:
    target = os.path.abspath(path)
    if not os.path.isfile(target):
        raise FileNotFoundError("File not found")
    if is_binary_file(target):
        raise ValueError("File biner / arsip tidak dapat dibuka di text editor. Silakan gunakan tombol Extract atau Download.")
    if os.path.getsize(target) > max_size:
        raise ValueError("File terlalu besar untuk dibuka di web (>2MB)")

    with open(target, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    return {"path": target, "content": content}

def save_file(path: str, content: str) -> Dict:
    target = os.path.abspath(path)
    # Create backup first if exists
    if os.path.exists(target):
        try:
            with open(target + ".bak", "w", encoding="utf-8") as bf:
                with open(target, "r", encoding="utf-8") as orig:
                    bf.write(orig.read())
        except Exception:
            pass

    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return {"success": True, "message": f"File {os.path.basename(target)} saved successfully"}

def upload_file(target_dir: str, filename: str, content: bytes) -> Dict:
    dest_dir = os.path.abspath(target_dir)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)

    dest_file = os.path.join(dest_dir, filename)
    with open(dest_file, "wb") as f:
        f.write(content)

    return {
        "success": True,
        "message": f"File {filename} uploaded successfully ({len(content)} bytes)",
        "path": dest_file,
        "size": len(content)
    }

def extract_archive(archive_path: str, destination: Optional[str] = None) -> Dict:
    src = os.path.abspath(archive_path)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"Archive file not found: {archive_path}")

    dest = os.path.abspath(destination) if destination and destination.strip() else os.path.dirname(src)
    os.makedirs(dest, exist_ok=True)

    lower_src = src.lower()
    cmd = None

    if lower_src.endswith(".zip"):
        cmd = ["unzip", "-o", "-q", src, "-d", dest]
    elif lower_src.endswith((".tar.gz", ".tgz")):
        cmd = ["tar", "-xzf", src, "-C", dest]
    elif lower_src.endswith((".tar.bz2", ".tbz2")):
        cmd = ["tar", "-xjf", src, "-C", dest]
    elif lower_src.endswith((".tar.xz", ".txz")):
        cmd = ["tar", "-xJf", src, "-C", dest]
    elif lower_src.endswith(".tar"):
        cmd = ["tar", "-xf", src, "-C", dest]
    elif lower_src.endswith(".rar"):
        cmd = ["unrar", "x", "-o+", "-inul", src, f"{dest}/"]
    elif lower_src.endswith(".7z"):
        cmd = ["7z", "x", "-y", f"-o{dest}", src]
    elif lower_src.endswith(".gz"):
        target_in_dest = os.path.join(dest, os.path.basename(src))
        if os.path.abspath(target_in_dest) != src:
            shutil.copy2(src, target_in_dest)
        cmd = ["gunzip", "-f", "-k", target_in_dest]
    elif lower_src.endswith(".bz2"):
        target_in_dest = os.path.join(dest, os.path.basename(src))
        if os.path.abspath(target_in_dest) != src:
            shutil.copy2(src, target_in_dest)
        cmd = ["bunzip2", "-f", "-k", target_in_dest]
    elif lower_src.endswith(".xz"):
        target_in_dest = os.path.join(dest, os.path.basename(src))
        if os.path.abspath(target_in_dest) != src:
            shutil.copy2(src, target_in_dest)
        cmd = ["unxz", "-f", "-k", target_in_dest]
    else:
        raise ValueError("Unsupported archive format. Supported formats: .zip, .tar.gz, .tgz, .tar.bz2, .tar.xz, .tar, .rar, .7z, .gz, .bz2, .xz")

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip() or "Unknown extraction error"
        raise RuntimeError(f"Extraction failed (code {res.returncode}): {err}")

    return {
        "success": True,
        "message": f"Berhasil mengekstrak {os.path.basename(src)} ke {dest}",
        "destination": dest
    }
