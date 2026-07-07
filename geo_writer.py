import os
import shutil
import piexif
from PIL import Image

EXIF_EXTS = {'.jpg', '.jpeg', '.tif', '.tiff'}


def _to_dms(decimal):
    """Return (is_negative, deg_rational, min_rational, sec_rational)."""
    neg = decimal < 0
    v = abs(decimal)
    d = int(v)
    m_f = (v - d) * 60
    m = int(m_f)
    s = (m_f - m) * 60
    return neg, (d, 1), (m, 1), (round(s * 1_000_000), 1_000_000)


def write_gps_exif(src_path: str, dst_path: str, lat: float, lon: float, alt=None):
    ext = os.path.splitext(src_path)[1].lower()
    if ext not in EXIF_EXTS:
        shutil.copy2(src_path, dst_path)
        return

    try:
        exif_dict = piexif.load(src_path)
    except Exception:
        exif_dict = {'0th': {}, 'Exif': {}, 'GPS': {}, '1st': {}, 'thumbnail': None}

    lat_neg, ld, lm, ls = _to_dms(lat)
    lon_neg, od, om, os_ = _to_dms(lon)

    gps = {
        piexif.GPSIFD.GPSVersionID: (2, 0, 0, 0),
        piexif.GPSIFD.GPSLatitudeRef: b'S' if lat_neg else b'N',
        piexif.GPSIFD.GPSLatitude: [ld, lm, ls],
        piexif.GPSIFD.GPSLongitudeRef: b'W' if lon_neg else b'E',
        piexif.GPSIFD.GPSLongitude: [od, om, os_],
    }
    if alt is not None:
        a = float(alt)
        gps[piexif.GPSIFD.GPSAltitudeRef] = 1 if a < 0 else 0
        gps[piexif.GPSIFD.GPSAltitude] = (round(abs(a) * 100), 100)

    exif_dict['GPS'] = gps

    try:
        exif_bytes = piexif.dump(exif_dict)
        img = Image.open(src_path)
        img.save(dst_path, exif=exif_bytes)
    except Exception:
        shutil.copy2(src_path, dst_path)
