//! A minimal, dependency-free ZIP *reader* for OPC packages — the counterpart
//! to the back-end's STORE writer. It walks the central directory to enumerate
//! entries and extracts the STORE (uncompressed) ones; a DEFLATE entry (from a
//! foreign `.docx`) is enumerated with `data = None` (content not inspected).

/// One archive member. `data` is `None` when the entry is compressed.
pub struct Entry {
    pub name: String,
    pub data: Option<Vec<u8>>,
}

fn u16le(b: &[u8], i: usize) -> Option<usize> {
    Some(u16::from_le_bytes([*b.get(i)?, *b.get(i + 1)?]) as usize)
}
fn u32le(b: &[u8], i: usize) -> Option<usize> {
    Some(u32::from_le_bytes([*b.get(i)?, *b.get(i + 1)?, *b.get(i + 2)?, *b.get(i + 3)?]) as usize)
}

/// Read a ZIP archive's entries (STORE extracted, DEFLATE enumerated).
pub fn read(bytes: &[u8]) -> Result<Vec<Entry>, String> {
    if bytes.len() < 22 || &bytes[..2] != b"PK" {
        return Err("missing PK signature".into());
    }
    // Locate the End Of Central Directory record (0x06054b50), scanning back
    // over a possible trailing comment.
    let eocd = (0..=bytes.len().saturating_sub(22))
        .rev()
        .find(|&i| bytes[i..].starts_with(&[0x50, 0x4b, 0x05, 0x06]))
        .ok_or("no end-of-central-directory record")?;
    let count = u16le(bytes, eocd + 10).ok_or("truncated EOCD")?;
    let mut off = u32le(bytes, eocd + 16).ok_or("truncated EOCD")?;

    let mut entries = Vec::with_capacity(count);
    for _ in 0..count {
        if !bytes[off..].starts_with(&[0x50, 0x4b, 0x01, 0x02]) {
            return Err("bad central-directory signature".into());
        }
        let method = u16le(bytes, off + 10).ok_or("truncated CD record")?;
        let comp_size = u32le(bytes, off + 20).ok_or("truncated CD record")?;
        let name_len = u16le(bytes, off + 28).ok_or("truncated CD record")?;
        let extra_len = u16le(bytes, off + 30).ok_or("truncated CD record")?;
        let comment_len = u16le(bytes, off + 32).ok_or("truncated CD record")?;
        let local_off = u32le(bytes, off + 42).ok_or("truncated CD record")?;
        let name_start = off + 46;
        let name = bytes
            .get(name_start..name_start + name_len)
            .ok_or("truncated CD filename")?;
        let name = String::from_utf8_lossy(name).into_owned();

        // Extract STORE data via the local file header.
        let data = if method == 0 {
            read_stored(bytes, local_off, comp_size)?
        } else {
            None
        };
        entries.push(Entry { name, data });
        off = name_start + name_len + extra_len + comment_len;
    }
    Ok(entries)
}

fn read_stored(bytes: &[u8], local_off: usize, size: usize) -> Result<Option<Vec<u8>>, String> {
    if !bytes[local_off..].starts_with(&[0x50, 0x4b, 0x03, 0x04]) {
        return Err("bad local-file-header signature".into());
    }
    let name_len = u16le(bytes, local_off + 26).ok_or("truncated local header")?;
    let extra_len = u16le(bytes, local_off + 28).ok_or("truncated local header")?;
    let data_start = local_off + 30 + name_len + extra_len;
    let data = bytes
        .get(data_start..data_start + size)
        .ok_or("truncated entry data")?;
    Ok(Some(data.to_vec()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_nothing_from_garbage() {
        assert!(read(b"not a zip at all").is_err());
    }
}
