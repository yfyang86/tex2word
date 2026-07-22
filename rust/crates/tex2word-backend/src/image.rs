//! Minimal, dependency-free raster-image inspection for `\includegraphics`.
//!
//! Detects the format from the file's magic bytes (never the extension), reads
//! the intrinsic pixel size from the header, and converts a graphicx size
//! option (`width=`, `height=`, `scale=`) into OOXML EMU extents. Only the
//! formats Word embeds natively (PNG, JPEG, GIF) are recognised; anything else
//! (PDF, EPS, TikZ output) returns `None` so the caller falls back to a text
//! placeholder.

/// English Metric Units per pixel at 96 DPI (914400 EMU/inch ÷ 96).
const EMU_PER_PX: u64 = 9525;
/// Text width of the default page (8.5in − 2×1in margins = 6.5in) in EMU.
const TEXT_WIDTH_EMU: u64 = 5_943_600;

/// A recognised raster image: its OOXML extension and intrinsic pixel size.
pub struct Probed {
    pub ext: &'static str,
    pub width: u32,
    pub height: u32,
}

/// Identify a raster image and read its intrinsic pixel dimensions.
pub fn probe(d: &[u8]) -> Option<Probed> {
    if d.len() >= 24 && d[..8] == [0x89, b'P', b'N', b'G', b'\r', b'\n', 0x1a, b'\n'] {
        let (width, height) = png_size(d)?;
        return Some(Probed {
            ext: "png",
            width,
            height,
        });
    }
    if d.len() >= 4 && d[0] == 0xFF && d[1] == 0xD8 && d[2] == 0xFF {
        let (width, height) = jpeg_size(d)?;
        return Some(Probed {
            ext: "jpeg",
            width,
            height,
        });
    }
    if d.len() >= 10 && (d[..6] == *b"GIF87a" || d[..6] == *b"GIF89a") {
        let width = u16::from_le_bytes([d[6], d[7]]) as u32;
        let height = u16::from_le_bytes([d[8], d[9]]) as u32;
        return Some(Probed {
            ext: "gif",
            width,
            height,
        });
    }
    None
}

/// PNG: the IHDR chunk's width/height are big-endian u32 at bytes 16 and 20.
fn png_size(d: &[u8]) -> Option<(u32, u32)> {
    let w = u32::from_be_bytes([d[16], d[17], d[18], d[19]]);
    let h = u32::from_be_bytes([d[20], d[21], d[22], d[23]]);
    Some((w, h))
}

/// JPEG: walk the marker segments to the first Start-Of-Frame (SOFn), whose
/// payload carries the height then width as big-endian u16.
fn jpeg_size(d: &[u8]) -> Option<(u32, u32)> {
    let mut i = 2;
    while i + 1 < d.len() {
        if d[i] != 0xFF {
            i += 1;
            continue;
        }
        let marker = d[i + 1];
        // Padding fill byte, or standalone markers (RSTn, SOI/EOI, TEM): no length.
        if marker == 0xFF {
            i += 1;
            continue;
        }
        if (0xD0..=0xD9).contains(&marker) || marker == 0x01 {
            i += 2;
            continue;
        }
        if i + 3 >= d.len() {
            break;
        }
        let len = ((d[i + 2] as usize) << 8) | d[i + 3] as usize;
        // SOF0..SOF15 hold the frame size, except DHT(C4)/JPG(C8)/DAC(CC).
        if (0xC0..=0xCF).contains(&marker) && marker != 0xC4 && marker != 0xC8 && marker != 0xCC {
            if i + 9 <= d.len() {
                let h = ((d[i + 5] as u32) << 8) | d[i + 6] as u32;
                let w = ((d[i + 7] as u32) << 8) | d[i + 8] as u32;
                return Some((w, h));
            }
            return None;
        }
        i += 2 + len;
    }
    None
}

/// Compute the display extent `(cx, cy)` in EMU from the graphicx option string
/// and the intrinsic pixel size. `width=`/`height=` accept LaTeX lengths
/// (`\textwidth` fractions, `cm`/`mm`/`in`/`pt`/`bp`/`px`); `scale=` multiplies
/// the intrinsic size. With no size option the intrinsic size (at 96 DPI) wins.
pub fn extent(options: &str, width_px: u32, height_px: u32) -> (u64, u64) {
    let iw = (width_px.max(1) as u64) * EMU_PER_PX;
    let ih = (height_px.max(1) as u64) * EMU_PER_PX;
    let mut w = None;
    let mut h = None;
    let mut scale = None;
    for kv in options.split(',') {
        let kv = kv.trim();
        if let Some(v) = kv.strip_prefix("width=") {
            w = parse_len(v.trim());
        } else if let Some(v) = kv.strip_prefix("height=") {
            h = parse_len(v.trim());
        } else if let Some(v) = kv.strip_prefix("scale=") {
            scale = v.trim().parse::<f64>().ok();
        }
    }
    if let Some(s) = scale.filter(|s| *s > 0.0) {
        return (((iw as f64) * s) as u64, ((ih as f64) * s) as u64);
    }
    // Scale the missing dimension to preserve the aspect ratio (u128 to be safe).
    let by_w = |cw: u64| (cw as u128 * ih as u128 / iw.max(1) as u128) as u64;
    let by_h = |ch: u64| (ch as u128 * iw as u128 / ih.max(1) as u128) as u64;
    match (w, h) {
        (Some(cw), Some(ch)) => (cw, ch),
        (Some(cw), None) => (cw, by_w(cw)),
        (None, Some(ch)) => (by_h(ch), ch),
        (None, None) => (iw, ih),
    }
}

/// Parse a LaTeX length (`0.5\textwidth`, `3cm`, `120pt`, …) to EMU.
fn parse_len(v: &str) -> Option<u64> {
    let idx = v
        .find(|c: char| !(c.is_ascii_digit() || c == '.' || c == '-' || c == '+'))
        .unwrap_or(v.len());
    let (num_s, unit) = v.split_at(idx);
    let num: f64 = num_s.trim().parse().ok()?;
    let unit = unit.trim();
    let emu = match unit {
        "\\textwidth" | "\\linewidth" | "\\columnwidth" | "\\hsize" | "\\textheight" => {
            num * TEXT_WIDTH_EMU as f64
        }
        "cm" => num * 360_000.0,
        "mm" => num * 36_000.0,
        "in" => num * 914_400.0,
        "pt" | "bp" => num * 12_700.0,
        "px" => num * EMU_PER_PX as f64,
        "em" => num * 12.0 * 12_700.0,
        _ => return None,
    };
    (emu >= 0.0).then_some(emu as u64)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A tiny 1×1 PNG (89 50 4E 47 … IHDR w=1 h=1).
    const PNG_1X1: &[u8] = &[
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, // signature
        0x00, 0x00, 0x00, 0x0D, b'I', b'H', b'D', b'R', // IHDR length + tag
        0x00, 0x00, 0x00, 0x07, // width = 7
        0x00, 0x00, 0x00, 0x03, // height = 3
        0x08, 0x06, 0x00, 0x00, 0x00, // bit depth etc.
    ];

    #[test]
    fn probes_png() {
        let p = probe(PNG_1X1).expect("png");
        assert_eq!(p.ext, "png");
        assert_eq!((p.width, p.height), (7, 3));
    }

    #[test]
    fn probes_jpeg_sof() {
        // FFD8 (SOI) then a SOF0 segment: FFC0, len=0011, prec, h=0x0004, w=0x0006
        let jpg: &[u8] = &[
            0xFF, 0xD8, 0xFF, 0xC0, 0x00, 0x11, 0x08, 0x00, 0x04, 0x00, 0x06, 0x03,
        ];
        let p = probe(jpg).expect("jpeg");
        assert_eq!(p.ext, "jpeg");
        assert_eq!((p.width, p.height), (6, 4));
    }

    #[test]
    fn unsupported_returns_none() {
        assert!(probe(b"%PDF-1.5").is_none());
        assert!(probe(b"not an image").is_none());
    }

    #[test]
    fn extent_intrinsic_and_scaled() {
        // intrinsic: 100px -> 100*9525 EMU
        assert_eq!(extent("", 100, 50), (100 * 9525, 50 * 9525));
        // scale halves both
        assert_eq!(extent("scale=0.5", 100, 50), (50 * 9525, 25 * 9525));
    }

    #[test]
    fn extent_width_keeps_aspect() {
        // width = half text width; height scales to keep 2:1 aspect
        let (cx, cy) = extent("width=0.5\\textwidth", 200, 100);
        assert_eq!(cx, 5_943_600 / 2);
        assert_eq!(cy, cx / 2); // 2:1 aspect preserved
    }

    #[test]
    fn extent_absolute_units() {
        assert_eq!(extent("width=3cm", 100, 100).0, 1_080_000);
        assert_eq!(extent("width=2in", 100, 100).0, 1_828_800);
    }
}
