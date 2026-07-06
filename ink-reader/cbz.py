import os
import zipfile


def build_cbz(images: list[tuple[str, bytes]], cbz_dest: str, cover_dest: str) -> tuple[int, int]:
    if not images:
        raise ValueError("no images")
    part = cbz_dest + ".part"
    with zipfile.ZipFile(part, "w", zipfile.ZIP_STORED) as out:
        for i, (ext, data) in enumerate(images, 1):
            out.writestr(f"{i:03d}{ext}", data)
    os.replace(part, cbz_dest)
    with open(cover_dest, "wb") as f:
        f.write(images[0][1])
    return len(images), os.path.getsize(cbz_dest)
