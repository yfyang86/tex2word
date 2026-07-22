//! OOXML back-end: assemble the IR [`Document`] into a `.docx` byte buffer.

mod ooxml;
mod zip;

use tex2word_ir::Document;
use zip::Entry;

/// Convert an IR document into a `.docx` (an OPC ZIP of the WordprocessingML
/// parts). The output is deterministic for a given input.
pub fn to_docx(doc: &Document) -> Vec<u8> {
    let entries = vec![
        Entry {
            name: "[Content_Types].xml".into(),
            data: ooxml::CONTENT_TYPES_XML.as_bytes().to_vec(),
        },
        Entry {
            name: "_rels/.rels".into(),
            data: ooxml::ROOT_RELS_XML.as_bytes().to_vec(),
        },
        Entry {
            name: "word/document.xml".into(),
            data: ooxml::document_xml(doc).into_bytes(),
        },
        Entry {
            name: "word/_rels/document.xml.rels".into(),
            data: ooxml::DOC_RELS_XML.as_bytes().to_vec(),
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
    zip::build(&entries)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tex2word_ir::{Block, Inline};

    #[test]
    fn docx_is_a_zip_with_document_part() {
        let doc = Document {
            title: None,
            blocks: vec![Block::Paragraph {
                inlines: vec![Inline::Text("hello".into())],
            }],
            ..Default::default()
        };
        let bytes = to_docx(&doc);
        assert_eq!(&bytes[..2], b"PK");
        // the raw document.xml text is present (STORE = no compression)
        let text = String::from_utf8_lossy(&bytes);
        assert!(text.contains("word/document.xml"));
        assert!(text.contains("hello"));
    }
}
