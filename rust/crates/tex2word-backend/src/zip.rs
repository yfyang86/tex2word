//! A minimal, dependency-free ZIP writer (STORE method) for the `.docx` OPC
//! container, plus a table-driven CRC-32. `.docx` is a ZIP of XML parts; STORE
//! (no compression) keeps the writer tiny and the output deterministic. A
//! production build may swap in the `zip` crate for DEFLATE — see the roadmap.

/// One archive member.
pub struct Entry {
    pub name: String,
    pub data: Vec<u8>,
}

fn crc32(data: &[u8]) -> u32 {
    // Standard CRC-32 (polynomial 0xEDB88320), computed with a per-call table.
    let mut table = [0u32; 256];
    let mut n = 0;
    while n < 256 {
        let mut c = n as u32;
        let mut k = 0;
        while k < 8 {
            c = if c & 1 != 0 {
                0xEDB8_8320 ^ (c >> 1)
            } else {
                c >> 1
            };
            k += 1;
        }
        table[n] = c;
        n += 1;
    }
    let mut crc = 0xFFFF_FFFFu32;
    for &b in data {
        crc = table[((crc ^ b as u32) & 0xFF) as usize] ^ (crc >> 8);
    }
    crc ^ 0xFFFF_FFFF
}

fn u16le(out: &mut Vec<u8>, v: u16) {
    out.extend_from_slice(&v.to_le_bytes());
}
fn u32le(out: &mut Vec<u8>, v: u32) {
    out.extend_from_slice(&v.to_le_bytes());
}

/// Build a ZIP archive (STORE) from the given entries. Output is deterministic
/// (fixed DOS timestamp), so identical input yields byte-identical `.docx`.
pub fn build(entries: &[Entry]) -> Vec<u8> {
    let mut out: Vec<u8> = Vec::new();
    let mut central: Vec<u8> = Vec::new();
    // Fixed DOS date/time (1980-01-01 00:00:00) for reproducibility.
    let dos_time: u16 = 0;
    let dos_date: u16 = 0x0021;

    for e in entries {
        let crc = crc32(&e.data);
        let size = e.data.len() as u32;
        let name = e.name.as_bytes();
        let offset = out.len() as u32;

        // ---- local file header ----
        u32le(&mut out, 0x0403_4b50);
        u16le(&mut out, 20); // version needed
        u16le(&mut out, 0); // flags
        u16le(&mut out, 0); // method: STORE
        u16le(&mut out, dos_time);
        u16le(&mut out, dos_date);
        u32le(&mut out, crc);
        u32le(&mut out, size); // compressed
        u32le(&mut out, size); // uncompressed
        u16le(&mut out, name.len() as u16);
        u16le(&mut out, 0); // extra len
        out.extend_from_slice(name);
        out.extend_from_slice(&e.data);

        // ---- central directory record ----
        u32le(&mut central, 0x0201_4b50);
        u16le(&mut central, 20); // version made by
        u16le(&mut central, 20); // version needed
        u16le(&mut central, 0); // flags
        u16le(&mut central, 0); // method
        u16le(&mut central, dos_time);
        u16le(&mut central, dos_date);
        u32le(&mut central, crc);
        u32le(&mut central, size);
        u32le(&mut central, size);
        u16le(&mut central, name.len() as u16);
        u16le(&mut central, 0); // extra
        u16le(&mut central, 0); // comment
        u16le(&mut central, 0); // disk number start
        u16le(&mut central, 0); // internal attrs
        u32le(&mut central, 0); // external attrs
        u32le(&mut central, offset);
        central.extend_from_slice(name);
    }

    let central_offset = out.len() as u32;
    let central_size = central.len() as u32;
    out.extend_from_slice(&central);

    // ---- end of central directory ----
    u32le(&mut out, 0x0605_4b50);
    u16le(&mut out, 0); // disk number
    u16le(&mut out, 0); // disk with central dir
    u16le(&mut out, entries.len() as u16);
    u16le(&mut out, entries.len() as u16);
    u32le(&mut out, central_size);
    u32le(&mut out, central_offset);
    u16le(&mut out, 0); // comment len
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc32_known_value() {
        // CRC-32 of "123456789" is 0xCBF43926 (a standard check value).
        assert_eq!(crc32(b"123456789"), 0xCBF4_3926);
    }

    #[test]
    fn archive_has_zip_signature_and_is_deterministic() {
        let e = [Entry {
            name: "a.txt".into(),
            data: b"hello".to_vec(),
        }];
        let z1 = build(&e);
        let z2 = build(&e);
        assert_eq!(&z1[..2], b"PK"); // local file header signature
        assert_eq!(z1, z2); // reproducible
    }
}
