//! OOXML back-end: assemble the IR [`Document`] into a `.docx` byte buffer.

mod fields;
mod image;
mod ooxml;
mod zip;

use std::path::Path;

use tex2word_ir::Document;
use zip::Entry;

pub use ooxml::PageGeometry;

/// Convert an IR document into a `.docx` (default US-Letter geometry).
pub fn to_docx(doc: &Document, base_dir: &Path) -> Vec<u8> {
    to_docx_with(doc, base_dir, &PageGeometry::default())
}

/// Convert an IR document into a `.docx` (an OPC ZIP of the WordprocessingML
/// parts) with explicit page geometry (e.g. from a `--reference-doc`).
/// `\includegraphics` images are read relative to `base_dir` and embedded as
/// `word/media/*` parts. The output is deterministic for a given input.
pub fn to_docx_with(doc: &Document, base_dir: &Path, page: &PageGeometry) -> Vec<u8> {
    let pkg = ooxml::build_package(doc, base_dir, page);
    let mut entries = vec![
        Entry {
            name: "[Content_Types].xml".into(),
            data: pkg.content_types_xml.into_bytes(),
        },
        Entry {
            name: "_rels/.rels".into(),
            data: ooxml::ROOT_RELS_XML.as_bytes().to_vec(),
        },
        Entry {
            name: "word/document.xml".into(),
            data: pkg.document_xml.into_bytes(),
        },
        Entry {
            name: "word/_rels/document.xml.rels".into(),
            data: pkg.doc_rels_xml.into_bytes(),
        },
        Entry {
            name: "word/styles.xml".into(),
            data: ooxml::styles_xml().into_bytes(),
        },
        Entry {
            name: "word/numbering.xml".into(),
            data: ooxml::NUMBERING_XML.as_bytes().to_vec(),
        },
    ];
    for m in pkg.media {
        entries.push(Entry {
            name: m.part_name,
            data: m.data,
        });
    }
    zip::build(&entries)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tex2word_ir::{Block, Inline};

    #[test]
    fn includegraphics_embeds_media_rel_and_drawing() {
        use std::fs;
        // A 7x3 PNG header (signature + IHDR dims); enough for probing.
        let png: &[u8] = &[
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, b'I', b'H',
            b'D', b'R', 0x00, 0x00, 0x00, 0x07, 0x00, 0x00, 0x00, 0x03, 0x08, 0x06, 0x00, 0x00,
            0x00,
        ];
        let dir = std::env::temp_dir().join(format!("t2w_img_{}", std::process::id()));
        let _ = fs::create_dir_all(&dir);
        fs::write(dir.join("pic.png"), png).unwrap();

        let doc = Document {
            blocks: vec![Block::Paragraph {
                inlines: vec![Inline::Image {
                    path: "pic.png".into(),
                    options: "width=2in".into(),
                }],
            }],
            ..Default::default()
        };
        let bytes = to_docx(&doc, &dir);
        let _ = fs::remove_dir_all(&dir);
        let text = String::from_utf8_lossy(&bytes);
        // media part embedded, relationship + content type declared, drawing emitted
        assert!(text.contains("word/media/image1.png"));
        assert!(text.contains("r:embed=\"rId3\""));
        assert!(text.contains("<w:drawing>"));
        assert!(text.contains("Extension=\"png\" ContentType=\"image/png\""));
        assert!(text.contains("Target=\"media/image1.png\""));
        // width=2in -> 1828800 EMU (aspect keeps cy = cx * 3/7)
        assert!(text.contains("cx=\"1828800\""));
        assert!(!text.contains("[image:")); // no placeholder fallback
    }

    #[test]
    fn page_geometry_applies_to_sectpr() {
        let doc = Document {
            blocks: vec![Block::Paragraph {
                inlines: vec![Inline::Text("x".into())],
            }],
            ..Default::default()
        };
        let letter = String::from_utf8_lossy(&to_docx(&doc, Path::new("."))).into_owned();
        assert!(letter.contains("w:w=\"12240\" w:h=\"15840\""));
        let a4 = to_docx_with(&doc, Path::new("."), &PageGeometry::a4());
        let a4 = String::from_utf8_lossy(&a4);
        assert!(a4.contains("w:w=\"11906\" w:h=\"16838\""));
    }

    #[test]
    fn docx_is_a_zip_with_document_part() {
        let doc = Document {
            title: None,
            blocks: vec![Block::Paragraph {
                inlines: vec![Inline::Text("hello".into())],
            }],
            ..Default::default()
        };
        let bytes = to_docx(&doc, Path::new("."));
        assert_eq!(&bytes[..2], b"PK");
        // the raw document.xml text is present (STORE = no compression)
        let text = String::from_utf8_lossy(&bytes);
        assert!(text.contains("word/document.xml"));
        assert!(text.contains("hello"));
    }
}
