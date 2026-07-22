//! OOXML (WordprocessingML) generation: IR -> the XML parts of a `.docx`.
//!
//! Emits `word/document.xml` (paragraphs, headings, styled runs, lists via
//! `numbering.xml`, quotes, and structured OMML math via the `tex2word-math`
//! crate) plus the fixed package parts (`[Content_Types].xml`, relationships,
//! `styles.xml`, `numbering.xml`). Tables, figures and live fields are later
//! milestones.

use tex2word_ir::{Block, Document, EmphasisKind, Inline, Table, TableAlign};

const W_NS: &str = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const M_NS: &str = "http://schemas.openxmlformats.org/officeDocument/2006/math";

/// Escape XML text content / attribute values.
fn escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            _ => out.push(c),
        }
    }
    out
}

#[derive(Default, Clone, Copy)]
struct RunProps {
    bold: bool,
    italic: bool,
    tt: bool,
    underline: bool,
    smallcaps: bool,
    superscript: bool,
    subscript: bool,
}

impl RunProps {
    fn is_plain(&self) -> bool {
        !(self.bold
            || self.italic
            || self.tt
            || self.underline
            || self.smallcaps
            || self.superscript
            || self.subscript)
    }

    fn rpr(&self) -> String {
        if self.is_plain() {
            return String::new();
        }
        let mut s = String::from("<w:rPr>");
        if self.bold {
            s.push_str("<w:b/>");
        }
        if self.italic {
            s.push_str("<w:i/>");
        }
        if self.smallcaps {
            s.push_str("<w:smallCaps/>");
        }
        if self.underline {
            s.push_str("<w:u w:val=\"single\"/>");
        }
        if self.tt {
            s.push_str("<w:rFonts w:ascii=\"Consolas\" w:hAnsi=\"Consolas\" w:cs=\"Consolas\"/>");
        }
        if self.superscript {
            s.push_str("<w:vertAlign w:val=\"superscript\"/>");
        } else if self.subscript {
            s.push_str("<w:vertAlign w:val=\"subscript\"/>");
        }
        s.push_str("</w:rPr>");
        s
    }
}

fn render_run(text: &str, rp: RunProps, out: &mut String) {
    out.push_str("<w:r>");
    out.push_str(&rp.rpr());
    out.push_str("<w:t xml:space=\"preserve\">");
    out.push_str(&escape(text));
    out.push_str("</w:t></w:r>");
}

fn render_math(latex: &str, out: &mut String) {
    // Structured OMML via the math engine (fractions, scripts, roots, symbols…).
    out.push_str(&tex2word_math::to_omath(latex));
}

fn render_inlines(inlines: &[Inline], rp: RunProps, out: &mut String) {
    for inl in inlines {
        match inl {
            Inline::Text(t) => render_run(t, rp, out),
            Inline::Emphasis { kind, inlines } => {
                let mut rp2 = rp;
                match kind {
                    EmphasisKind::Bold => rp2.bold = true,
                    EmphasisKind::Italic => rp2.italic = true,
                    EmphasisKind::Typewriter => rp2.tt = true,
                    EmphasisKind::Underline => rp2.underline = true,
                    EmphasisKind::SmallCaps => rp2.smallcaps = true,
                    EmphasisKind::Superscript => rp2.superscript = true,
                    EmphasisKind::Subscript => rp2.subscript = true,
                }
                render_inlines(inlines, rp2, out);
            }
            Inline::Math(m) => render_math(m, out),
            Inline::LineBreak => out.push_str("<w:r><w:br/></w:r>"),
        }
    }
}

fn render_paragraph(style: Option<&str>, inlines: &[Inline], out: &mut String) {
    out.push_str("<w:p>");
    if let Some(style) = style {
        out.push_str("<w:pPr><w:pStyle w:val=\"");
        out.push_str(style);
        out.push_str("\"/></w:pPr>");
    }
    render_inlines(inlines, RunProps::default(), out);
    out.push_str("</w:p>");
}

/// One list item -> a numbered/bulleted paragraph (numId 1 = bullet, 2 = decimal).
fn render_list_item(inlines: &[Inline], num_id: u32, out: &mut String) {
    out.push_str(
        "<w:p><w:pPr><w:pStyle w:val=\"ListParagraph\"/>\
         <w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"",
    );
    out.push_str(&num_id.to_string());
    out.push_str("\"/></w:numPr></w:pPr>");
    render_inlines(inlines, RunProps::default(), out);
    out.push_str("</w:p>");
}

fn render_block(block: &Block, out: &mut String) {
    match block {
        Block::Heading { level, inlines } => {
            let style = format!("Heading{}", level.clamp(&1, &9));
            render_paragraph(Some(&style), inlines, out);
        }
        Block::Paragraph { inlines } => render_paragraph(None, inlines, out),
        Block::List { ordered, items } => {
            let num_id = if *ordered { 2 } else { 1 };
            for item in items {
                render_list_item(item, num_id, out);
            }
        }
        Block::Quote(blocks) => {
            for b in blocks {
                match b {
                    Block::Paragraph { inlines } => render_paragraph(Some("Quote"), inlines, out),
                    other => render_block(other, out),
                }
            }
        }
        Block::Table(table) => render_table(table, out),
    }
}

/// Map a cell alignment to a `w:jc` justification value.
fn jc_val(align: TableAlign) -> &'static str {
    match align {
        TableAlign::Left => "left",
        TableAlign::Center => "center",
        TableAlign::Right => "right",
    }
}

/// Render a [`Table`] to a WordprocessingML `w:tbl` (single-line borders; header
/// rows repeat across pages; `\multicolumn` -> `w:gridSpan`).
fn render_table(table: &Table, out: &mut String) {
    // Grid column count: the widest row after expanding colspans.
    let ncols = table
        .rows
        .iter()
        .map(|r| r.cells.iter().map(|c| c.colspan.max(1)).sum::<usize>())
        .max()
        .unwrap_or(0)
        .max(table.colspec.len())
        .max(1);
    out.push_str("<w:tbl><w:tblPr><w:tblStyle w:val=\"TableGrid\"/>");
    out.push_str("<w:tblW w:w=\"0\" w:type=\"auto\"/>");
    out.push_str(concat!(
        "<w:tblBorders>",
        "<w:top w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "<w:left w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "<w:bottom w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "<w:right w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "<w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "</w:tblBorders></w:tblPr>",
    ));
    out.push_str("<w:tblGrid>");
    for _ in 0..ncols {
        out.push_str("<w:gridCol/>");
    }
    out.push_str("</w:tblGrid>");
    for row in &table.rows {
        out.push_str("<w:tr>");
        if row.is_header {
            out.push_str("<w:trPr><w:tblHeader/></w:trPr>");
        }
        for cell in &row.cells {
            out.push_str("<w:tc><w:tcPr>");
            if cell.colspan > 1 {
                out.push_str(&format!("<w:gridSpan w:val=\"{}\"/>", cell.colspan));
            }
            out.push_str("</w:tcPr>");
            // Cell body: a single paragraph justified per the column alignment.
            out.push_str("<w:p><w:pPr><w:jc w:val=\"");
            out.push_str(jc_val(cell.align));
            out.push_str("\"/></w:pPr>");
            render_inlines(&cell.inlines, RunProps::default(), out);
            out.push_str("</w:p></w:tc>");
        }
        out.push_str("</w:tr>");
    }
    out.push_str("</w:tbl>");
    // A trailing empty paragraph keeps a table from being the final body element
    // (Word requires a paragraph after a table / before sectPr).
    out.push_str("<w:p/>");
}

/// Render the IR document to `word/document.xml`.
pub fn document_xml(doc: &Document) -> String {
    let mut body = String::new();
    if let Some(title) = &doc.title {
        render_paragraph(Some("Title"), title, &mut body);
    }
    for author in &doc.authors {
        render_paragraph(Some("Subtitle"), author, &mut body);
    }
    if let Some(date) = &doc.date {
        render_paragraph(Some("Subtitle"), date, &mut body);
    }
    for block in &doc.blocks {
        render_block(block, &mut body);
    }
    format!(
        concat!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
            "<w:document xmlns:w=\"{w}\" xmlns:m=\"{m}\"><w:body>{body}",
            "<w:sectPr><w:pgSz w:w=\"12240\" w:h=\"15840\"/>",
            "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" ",
            "w:header=\"720\" w:footer=\"720\"/></w:sectPr></w:body></w:document>"
        ),
        w = W_NS,
        m = M_NS,
        body = body
    )
}

pub const CONTENT_TYPES_XML: &str = concat!(
    "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
    "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">",
    "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>",
    "<Default Extension=\"xml\" ContentType=\"application/xml\"/>",
    "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>",
    "<Override PartName=\"/word/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml\"/>",
    "<Override PartName=\"/word/numbering.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml\"/>",
    "</Types>"
);

pub const ROOT_RELS_XML: &str = concat!(
    "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
    "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">",
    "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>",
    "</Relationships>"
);

pub const DOC_RELS_XML: &str = concat!(
    "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
    "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">",
    "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>",
    "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering\" Target=\"numbering.xml\"/>",
    "</Relationships>"
);

/// Numbering definitions: abstractNum 0 = bullet (numId 1), 1 = decimal (numId 2).
pub const NUMBERING_XML: &str = concat!(
    "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
    "<w:numbering xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">",
    "<w:abstractNum w:abstractNumId=\"0\"><w:lvl w:ilvl=\"0\"><w:start w:val=\"1\"/>",
    "<w:numFmt w:val=\"bullet\"/><w:lvlText w:val=\"\u{2022}\"/><w:lvlJc w:val=\"left\"/>",
    "<w:pPr><w:ind w:left=\"720\" w:hanging=\"360\"/></w:pPr></w:lvl></w:abstractNum>",
    "<w:abstractNum w:abstractNumId=\"1\"><w:lvl w:ilvl=\"0\"><w:start w:val=\"1\"/>",
    "<w:numFmt w:val=\"decimal\"/><w:lvlText w:val=\"%1.\"/><w:lvlJc w:val=\"left\"/>",
    "<w:pPr><w:ind w:left=\"720\" w:hanging=\"360\"/></w:pPr></w:lvl></w:abstractNum>",
    "<w:num w:numId=\"1\"><w:abstractNumId w:val=\"0\"/></w:num>",
    "<w:num w:numId=\"2\"><w:abstractNumId w:val=\"1\"/></w:num>",
    "</w:numbering>"
);

/// Minimal styles: Normal + Title + Heading1..3 (mapped to Word's built-ins).
pub fn styles_xml() -> String {
    let mut s = String::from(concat!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
        "<w:styles xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">",
        "<w:style w:type=\"paragraph\" w:default=\"1\" w:styleId=\"Normal\"><w:name w:val=\"Normal\"/></w:style>",
        "<w:style w:type=\"paragraph\" w:styleId=\"Title\"><w:name w:val=\"Title\"/>",
        "<w:pPr><w:jc w:val=\"center\"/></w:pPr><w:rPr><w:b/><w:sz w:val=\"56\"/></w:rPr></w:style>",
        "<w:style w:type=\"paragraph\" w:styleId=\"Subtitle\"><w:name w:val=\"Subtitle\"/>",
        "<w:basedOn w:val=\"Normal\"/><w:next w:val=\"Normal\"/>",
        "<w:pPr><w:jc w:val=\"center\"/></w:pPr><w:rPr><w:sz w:val=\"28\"/></w:rPr></w:style>",
    ));
    for (id, sz) in [("Heading1", 36), ("Heading2", 30), ("Heading3", 26)] {
        s.push_str(&format!(
            "<w:style w:type=\"paragraph\" w:styleId=\"{id}\"><w:name w:val=\"{id}\"/>\
             <w:basedOn w:val=\"Normal\"/><w:next w:val=\"Normal\"/>\
             <w:rPr><w:b/><w:sz w:val=\"{sz}\"/></w:rPr></w:style>"
        ));
    }
    // ListParagraph (list items) and Quote (set-off, italic + indented).
    s.push_str(concat!(
        "<w:style w:type=\"paragraph\" w:styleId=\"ListParagraph\">",
        "<w:name w:val=\"List Paragraph\"/><w:basedOn w:val=\"Normal\"/></w:style>",
        "<w:style w:type=\"paragraph\" w:styleId=\"Quote\"><w:name w:val=\"Quote\"/>",
        "<w:basedOn w:val=\"Normal\"/><w:next w:val=\"Normal\"/>",
        "<w:pPr><w:ind w:left=\"720\" w:right=\"720\"/></w:pPr>",
        "<w:rPr><w:i/></w:rPr></w:style>",
    ));
    // TableGrid: a bordered table style (referenced by rendered w:tbl elements).
    s.push_str(concat!(
        "<w:style w:type=\"table\" w:styleId=\"TableGrid\"><w:name w:val=\"Table Grid\"/>",
        "<w:basedOn w:val=\"TableNormal\"/><w:tblPr>",
        "<w:tblBorders>",
        "<w:top w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "<w:left w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "<w:bottom w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "<w:right w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "<w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"auto\"/>",
        "</w:tblBorders></w:tblPr></w:style>",
        "<w:style w:type=\"table\" w:default=\"1\" w:styleId=\"TableNormal\">",
        "<w:name w:val=\"Normal Table\"/></w:style>",
    ));
    s.push_str("</w:styles>");
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn escapes_xml_special_chars() {
        assert_eq!(escape("a<b&c>\"d\""), "a&lt;b&amp;c&gt;&quot;d&quot;");
    }

    #[test]
    fn document_xml_has_runs_and_math() {
        let doc = Document {
            title: Some(vec![Inline::Text("T".into())]),
            blocks: vec![Block::Paragraph {
                inlines: vec![
                    Inline::Emphasis {
                        kind: EmphasisKind::Bold,
                        inlines: vec![Inline::Text("hi".into())],
                    },
                    Inline::Math("x".into()),
                ],
            }],
            ..Default::default()
        };
        let xml = document_xml(&doc);
        assert!(xml.contains("w:pStyle w:val=\"Title\""));
        assert!(xml.contains("<w:b/>"));
        assert!(xml.contains("<m:oMath>"));
    }

    #[test]
    fn table_renders_grid_header_and_span() {
        use tex2word_ir::{TableCell, TableRow};
        let table = Table {
            colspec: vec![TableAlign::Left, TableAlign::Right],
            rows: vec![
                TableRow {
                    is_header: true,
                    cells: vec![TableCell {
                        inlines: vec![Inline::Text("Head".into())],
                        colspan: 2,
                        align: TableAlign::Center,
                    }],
                },
                TableRow {
                    is_header: false,
                    cells: vec![
                        TableCell {
                            inlines: vec![Inline::Text("a".into())],
                            colspan: 1,
                            align: TableAlign::Left,
                        },
                        TableCell {
                            inlines: vec![Inline::Text("b".into())],
                            colspan: 1,
                            align: TableAlign::Right,
                        },
                    ],
                },
            ],
        };
        let doc = Document {
            blocks: vec![Block::Table(table)],
            ..Default::default()
        };
        let xml = document_xml(&doc);
        assert!(xml.contains("<w:tbl>"));
        assert_eq!(xml.matches("<w:gridCol/>").count(), 2); // 2-column grid
        assert!(xml.contains("<w:tblHeader/>")); // header row flagged
        assert!(xml.contains("<w:gridSpan w:val=\"2\"/>")); // multicolumn span
        assert!(xml.contains("<w:jc w:val=\"right\"/>")); // right-aligned cell
        assert_eq!(xml.matches("<w:tr>").count(), 2);
        // styles.xml must define the referenced TableGrid style
        assert!(styles_xml().contains("w:styleId=\"TableGrid\""));
    }

    #[test]
    fn small_caps_and_superscript_render() {
        let doc = Document {
            title: None,
            blocks: vec![Block::Paragraph {
                inlines: vec![
                    Inline::Emphasis {
                        kind: EmphasisKind::SmallCaps,
                        inlines: vec![Inline::Text("a".into())],
                    },
                    Inline::Emphasis {
                        kind: EmphasisKind::Superscript,
                        inlines: vec![Inline::Text("2".into())],
                    },
                ],
            }],
            ..Default::default()
        };
        let xml = document_xml(&doc);
        assert!(xml.contains("<w:smallCaps/>"));
        assert!(xml.contains("<w:vertAlign w:val=\"superscript\"/>"));
    }
}
