//! OOXML (WordprocessingML) generation: IR -> the XML parts of a `.docx`.
//!
//! Emits `word/document.xml` (paragraphs, headings, styled runs, lists via
//! `numbering.xml`, quotes, structured OMML math via the `tex2word-math` crate,
//! `w:tbl` tables with spans/merges, and figure/table floats with numbered
//! captions and embedded images) plus the package parts (`[Content_Types].xml`,
//! relationships, `styles.xml`, `numbering.xml`, `word/media/*`). Live fields
//! (SEQ/REF) and cross-references are later milestones.

use std::path::Path;

use tex2word_ir::{Block, Document, EmphasisKind, Float, FloatKind, Inline, Table, TableAlign};

use crate::image;

const W_NS: &str = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const M_NS: &str = "http://schemas.openxmlformats.org/officeDocument/2006/math";
const R_NS: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const WP_NS: &str = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing";
const A_NS: &str = "http://schemas.openxmlformats.org/drawingml/2006/main";
const PIC_NS: &str = "http://schemas.openxmlformats.org/drawingml/2006/picture";

/// One embedded media part (an image file) destined for `word/media/`.
pub struct MediaPart {
    pub part_name: String,
    pub data: Vec<u8>,
}

/// The rendered package parts that depend on the document body.
pub struct Package {
    pub document_xml: String,
    pub content_types_xml: String,
    pub doc_rels_xml: String,
    pub media: Vec<MediaPart>,
}

/// A resolved, embeddable image and its relationship/part identity.
struct Media {
    part_name: String, // word/media/image1.png
    target: String,    // media/image1.png (relative to word/_rels)
    ext: String,       // png | jpeg | gif
    rid: String,       // rId3, rId4, …
    data: Vec<u8>,
    width: u32,
    height: u32,
}

/// Reads and de-duplicates `\includegraphics` files, assigning each a media
/// part name and relationship id. Files that are missing or not a supported
/// raster image are skipped (the caller emits a text placeholder instead).
struct MediaRegistry<'a> {
    base_dir: &'a Path,
    items: Vec<Media>,
    seen: Vec<(String, usize)>,
}

impl<'a> MediaRegistry<'a> {
    fn new(base_dir: &'a Path) -> Self {
        Self {
            base_dir,
            items: Vec::new(),
            seen: Vec::new(),
        }
    }

    /// Resolve an image path to a media index, reading + probing it on first use.
    fn resolve(&mut self, path: &str) -> Option<usize> {
        if let Some(&(_, idx)) = self.seen.iter().find(|(p, _)| p == path) {
            return Some(idx);
        }
        let data = std::fs::read(self.base_dir.join(path)).ok()?;
        let probed = image::probe(&data)?;
        let n = self.items.len() + 1;
        let ext = probed.ext.to_string();
        let idx = self.items.len();
        self.items.push(Media {
            part_name: format!("word/media/image{n}.{ext}"),
            target: format!("media/image{n}.{ext}"),
            rid: format!("rId{}", n + 2), // rId1/rId2 = styles/numbering
            ext,
            data,
            width: probed.width,
            height: probed.height,
        });
        self.seen.push((path.to_string(), idx));
        Some(idx)
    }
}

/// Mutable render state: caption counters, the media registry, drawing ids.
struct Ctx<'a> {
    figure: u32,
    table: u32,
    drawing_id: u32,
    media: MediaRegistry<'a>,
}

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

fn render_inlines(inlines: &[Inline], rp: RunProps, ctx: &mut Ctx, out: &mut String) {
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
                render_inlines(inlines, rp2, ctx, out);
            }
            Inline::Math(m) => render_math(m, out),
            Inline::LineBreak => out.push_str("<w:r><w:br/></w:r>"),
            Inline::Image { path, options } => render_image(path, options, ctx, out),
        }
    }
}

/// Render an `\includegraphics` as an embedded `w:drawing`, or a `[image: …]`
/// text placeholder if the file is missing or an unsupported format.
fn render_image(path: &str, options: &str, ctx: &mut Ctx, out: &mut String) {
    if let Some(idx) = ctx.media.resolve(path) {
        let (rid, w, h) = {
            let m = &ctx.media.items[idx];
            (m.rid.clone(), m.width, m.height)
        };
        let (cx, cy) = image::extent(options, w, h);
        ctx.drawing_id += 1;
        emit_drawing(&rid, ctx.drawing_id, cx, cy, out);
    } else {
        out.push_str("<w:r><w:rPr><w:i/></w:rPr><w:t xml:space=\"preserve\">");
        out.push_str(&escape(&format!("[image: {path}]")));
        out.push_str("</w:t></w:r>");
    }
}

/// Emit an inline picture drawing referencing embed relationship `rid`, sized
/// `cx`×`cy` EMU. Relies on the `wp`/`a`/`pic`/`r` namespaces declared on the
/// document root.
fn emit_drawing(rid: &str, id: u32, cx: u64, cy: u64, out: &mut String) {
    out.push_str(&format!(
        concat!(
            "<w:r><w:drawing><wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">",
            "<wp:extent cx=\"{cx}\" cy=\"{cy}\"/>",
            "<wp:effectExtent l=\"0\" t=\"0\" r=\"0\" b=\"0\"/>",
            "<wp:docPr id=\"{id}\" name=\"Picture {id}\"/>",
            "<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect=\"1\"/></wp:cNvGraphicFramePr>",
            "<a:graphic><a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">",
            "<pic:pic><pic:nvPicPr><pic:cNvPr id=\"{id}\" name=\"Picture {id}\"/>",
            "<pic:cNvPicPr/></pic:nvPicPr>",
            "<pic:blipFill><a:blip r:embed=\"{rid}\"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>",
            "<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"{cx}\" cy=\"{cy}\"/></a:xfrm>",
            "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></pic:spPr>",
            "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
        ),
        cx = cx,
        cy = cy,
        id = id,
        rid = rid
    ));
}

fn render_paragraph(style: Option<&str>, inlines: &[Inline], ctx: &mut Ctx, out: &mut String) {
    render_paragraph_jc(style, None, inlines, ctx, out);
}

/// Like [`render_paragraph`] but with an optional `w:jc` justification.
fn render_paragraph_jc(
    style: Option<&str>,
    jc: Option<&str>,
    inlines: &[Inline],
    ctx: &mut Ctx,
    out: &mut String,
) {
    out.push_str("<w:p>");
    if style.is_some() || jc.is_some() {
        out.push_str("<w:pPr>");
        if let Some(style) = style {
            out.push_str("<w:pStyle w:val=\"");
            out.push_str(style);
            out.push_str("\"/>");
        }
        if let Some(jc) = jc {
            out.push_str("<w:jc w:val=\"");
            out.push_str(jc);
            out.push_str("\"/>");
        }
        out.push_str("</w:pPr>");
    }
    render_inlines(inlines, RunProps::default(), ctx, out);
    out.push_str("</w:p>");
}

/// One list item -> a numbered/bulleted paragraph (numId 1 = bullet, 2 = decimal).
fn render_list_item(inlines: &[Inline], num_id: u32, ctx: &mut Ctx, out: &mut String) {
    out.push_str(
        "<w:p><w:pPr><w:pStyle w:val=\"ListParagraph\"/>\
         <w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"",
    );
    out.push_str(&num_id.to_string());
    out.push_str("\"/></w:numPr></w:pPr>");
    render_inlines(inlines, RunProps::default(), ctx, out);
    out.push_str("</w:p>");
}

fn render_block(block: &Block, ctx: &mut Ctx, out: &mut String) {
    match block {
        Block::Heading { level, inlines } => {
            let style = format!("Heading{}", level.clamp(&1, &9));
            render_paragraph(Some(&style), inlines, ctx, out);
        }
        Block::Paragraph { inlines } => render_paragraph(None, inlines, ctx, out),
        Block::List { ordered, items } => {
            let num_id = if *ordered { 2 } else { 1 };
            for item in items {
                render_list_item(item, num_id, ctx, out);
            }
        }
        Block::Quote(blocks) => {
            for b in blocks {
                match b {
                    Block::Paragraph { inlines } => {
                        render_paragraph(Some("Quote"), inlines, ctx, out)
                    }
                    other => render_block(other, ctx, out),
                }
            }
        }
        Block::Table(table) => render_table(table, false, ctx, out),
        Block::Float(float) => render_float(float, ctx, out),
    }
}

/// Render a `figure`/`table` float: its content (centered if requested) followed
/// by a numbered caption paragraph.
fn render_float(float: &Float, ctx: &mut Ctx, out: &mut String) {
    for b in &float.content {
        match b {
            Block::Paragraph { inlines } => {
                render_paragraph_jc(None, float.centered.then_some("center"), inlines, ctx, out);
            }
            Block::Table(table) => render_table(table, float.centered, ctx, out),
            other => render_block(other, ctx, out),
        }
    }
    if let Some(cap) = &float.caption {
        let (prefix, num) = match float.kind {
            FloatKind::Figure => {
                ctx.figure += 1;
                ("Figure", ctx.figure)
            }
            FloatKind::Table => {
                ctx.table += 1;
                ("Table", ctx.table)
            }
        };
        out.push_str("<w:p><w:pPr><w:pStyle w:val=\"Caption\"/>");
        if float.centered {
            out.push_str("<w:jc w:val=\"center\"/>");
        }
        out.push_str("</w:pPr>");
        out.push_str(&format!(
            "<w:r><w:rPr><w:b/></w:rPr><w:t xml:space=\"preserve\">{prefix} {num}: </w:t></w:r>"
        ));
        render_inlines(cap, RunProps::default(), ctx, out);
        out.push_str("</w:p>");
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
/// rows repeat across pages; `\multicolumn` -> `w:gridSpan`; `center` -> the
/// table is centered on the page).
fn render_table(table: &Table, center: bool, ctx: &mut Ctx, out: &mut String) {
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
    if center {
        out.push_str("<w:jc w:val=\"center\"/>");
    }
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
    // Per grid-column countdown of remaining `\multirow` continuation rows.
    let mut pending = vec![0usize; ncols];
    for row in &table.rows {
        out.push_str("<w:tr>");
        if row.is_header {
            out.push_str("<w:trPr><w:tblHeader/></w:trPr>");
        }
        let mut gridcol = 0usize;
        for cell in &row.cells {
            let span = cell.colspan.max(1);
            let end = (gridcol + span).min(ncols);
            // Vertical-merge state: a \multirow starts a "restart"; a cell landing
            // on a column still counting down is a "continue".
            let vmerge = if cell.rowspan > 1 {
                for p in pending.iter_mut().take(end).skip(gridcol) {
                    *p = cell.rowspan - 1;
                }
                "<w:vMerge w:val=\"restart\"/>"
            } else if gridcol < ncols && pending[gridcol] > 0 {
                for p in pending.iter_mut().take(end).skip(gridcol) {
                    *p = p.saturating_sub(1);
                }
                "<w:vMerge/>"
            } else {
                ""
            };
            out.push_str("<w:tc><w:tcPr>");
            if span > 1 {
                out.push_str(&format!("<w:gridSpan w:val=\"{span}\"/>"));
            }
            out.push_str(vmerge);
            out.push_str("</w:tcPr>");
            // Cell body: a single paragraph justified per the column alignment.
            out.push_str("<w:p><w:pPr><w:jc w:val=\"");
            out.push_str(jc_val(cell.align));
            out.push_str("\"/></w:pPr>");
            render_inlines(&cell.inlines, RunProps::default(), ctx, out);
            out.push_str("</w:p></w:tc>");
            gridcol += span;
        }
        out.push_str("</w:tr>");
    }
    out.push_str("</w:tbl>");
    // A trailing empty paragraph keeps a table from being the final body element
    // (Word requires a paragraph after a table / before sectPr).
    out.push_str("<w:p/>");
}

/// Render the IR document to `word/document.xml` (images fall back to text
/// placeholders since no base directory is given). Used by unit tests; the
/// package builder [`build_package`] is the real entry point.
#[cfg(test)]
pub fn document_xml(doc: &Document) -> String {
    build_package(doc, Path::new(".")).document_xml
}

/// Render the body-dependent package parts: `word/document.xml`, the content
/// types, the document relationships, and any embedded media (images resolved
/// against `base_dir`).
pub fn build_package(doc: &Document, base_dir: &Path) -> Package {
    let mut ctx = Ctx {
        figure: 0,
        table: 0,
        drawing_id: 0,
        media: MediaRegistry::new(base_dir),
    };
    let mut body = String::new();
    if let Some(title) = &doc.title {
        render_paragraph(Some("Title"), title, &mut ctx, &mut body);
    }
    for author in &doc.authors {
        render_paragraph(Some("Subtitle"), author, &mut ctx, &mut body);
    }
    if let Some(date) = &doc.date {
        render_paragraph(Some("Subtitle"), date, &mut ctx, &mut body);
    }
    for block in &doc.blocks {
        render_block(block, &mut ctx, &mut body);
    }
    let document_xml = format!(
        concat!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
            "<w:document xmlns:w=\"{w}\" xmlns:m=\"{m}\" xmlns:r=\"{r}\" ",
            "xmlns:wp=\"{wp}\" xmlns:a=\"{a}\" xmlns:pic=\"{pic}\"><w:body>{body}",
            "<w:sectPr><w:pgSz w:w=\"12240\" w:h=\"15840\"/>",
            "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" ",
            "w:header=\"720\" w:footer=\"720\"/></w:sectPr></w:body></w:document>"
        ),
        w = W_NS,
        m = M_NS,
        r = R_NS,
        wp = WP_NS,
        a = A_NS,
        pic = PIC_NS,
        body = body
    );

    // Collect image relationships, content-type defaults, and media parts.
    let mut image_rels = String::new();
    let mut exts: Vec<String> = Vec::new();
    let mut media: Vec<MediaPart> = Vec::new();
    for m in &ctx.media.items {
        image_rels.push_str(&format!(
            "<Relationship Id=\"{}\" Type=\"{R_NS}/image\" Target=\"{}\"/>",
            m.rid, m.target
        ));
        if !exts.iter().any(|e| e == &m.ext) {
            exts.push(m.ext.clone());
        }
        media.push(MediaPart {
            part_name: m.part_name.clone(),
            data: m.data.clone(),
        });
    }

    Package {
        document_xml,
        content_types_xml: content_types_xml(&exts),
        doc_rels_xml: doc_rels_xml(&image_rels),
        media,
    }
}

/// The `[Content_Types].xml` part, with a `Default` for each embedded image ext.
fn content_types_xml(image_exts: &[String]) -> String {
    let mut s = String::from(concat!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">",
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>",
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>",
    ));
    for ext in image_exts {
        let ct = match ext.as_str() {
            "png" => "image/png",
            "jpeg" | "jpg" => "image/jpeg",
            "gif" => "image/gif",
            _ => continue,
        };
        s.push_str(&format!(
            "<Default Extension=\"{ext}\" ContentType=\"{ct}\"/>"
        ));
    }
    s.push_str(concat!(
        "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>",
        "<Override PartName=\"/word/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml\"/>",
        "<Override PartName=\"/word/numbering.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml\"/>",
        "</Types>"
    ));
    s
}

/// The `word/_rels/document.xml.rels` part: styles + numbering + image rels.
fn doc_rels_xml(image_rels: &str) -> String {
    format!(
        concat!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">",
            "<Relationship Id=\"rId1\" Type=\"{r}/styles\" Target=\"styles.xml\"/>",
            "<Relationship Id=\"rId2\" Type=\"{r}/numbering\" Target=\"numbering.xml\"/>",
            "{image_rels}</Relationships>"
        ),
        r = R_NS,
        image_rels = image_rels
    )
}

pub const ROOT_RELS_XML: &str = concat!(
    "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
    "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">",
    "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>",
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
        // Caption (figure/table captions): small text, spaced above.
        "<w:style w:type=\"paragraph\" w:styleId=\"Caption\"><w:name w:val=\"Caption\"/>",
        "<w:basedOn w:val=\"Normal\"/><w:next w:val=\"Normal\"/>",
        "<w:pPr><w:spacing w:before=\"120\" w:after=\"120\"/></w:pPr>",
        "<w:rPr><w:sz w:val=\"18\"/></w:rPr></w:style>",
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
                        rowspan: 1,
                        align: TableAlign::Center,
                    }],
                },
                TableRow {
                    is_header: false,
                    cells: vec![
                        TableCell {
                            inlines: vec![Inline::Text("a".into())],
                            colspan: 1,
                            rowspan: 1,
                            align: TableAlign::Left,
                        },
                        TableCell {
                            inlines: vec![Inline::Text("b".into())],
                            colspan: 1,
                            rowspan: 1,
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
    fn table_multirow_renders_vmerge() {
        use tex2word_ir::{TableCell, TableRow};
        let cell = |text: &str, rowspan: usize| TableCell {
            inlines: if text.is_empty() {
                vec![]
            } else {
                vec![Inline::Text(text.into())]
            },
            colspan: 1,
            rowspan,
            align: TableAlign::Left,
        };
        let table = Table {
            colspec: vec![TableAlign::Left, TableAlign::Left],
            rows: vec![
                TableRow {
                    is_header: false,
                    cells: vec![cell("Group", 2), cell("a", 1)],
                },
                TableRow {
                    is_header: false,
                    cells: vec![cell("", 1), cell("b", 1)],
                },
            ],
        };
        let doc = Document {
            blocks: vec![Block::Table(table)],
            ..Default::default()
        };
        let xml = document_xml(&doc);
        assert!(xml.contains("<w:vMerge w:val=\"restart\"/>")); // top cell starts merge
        assert!(xml.contains("<w:vMerge/>")); // placeholder continues merge
        assert_eq!(xml.matches("w:vMerge").count(), 2);
    }

    #[test]
    fn floats_number_captions_and_placeholder_image() {
        let fig = |n: &str| {
            Block::Float(Float {
                kind: FloatKind::Figure,
                content: vec![Block::Paragraph {
                    inlines: vec![Inline::Image {
                        path: format!("{n}.png"),
                        options: String::new(),
                    }],
                }],
                caption: Some(vec![Inline::Text(format!("Cap {n}"))]),
                centered: true,
            })
        };
        let tbl = Block::Float(Float {
            kind: FloatKind::Table,
            content: vec![],
            caption: Some(vec![Inline::Text("T".into())]),
            centered: false,
        });
        let doc = Document {
            blocks: vec![fig("a"), tbl, fig("b")],
            ..Default::default()
        };
        let xml = document_xml(&doc);
        // independent Figure / Table counters
        assert!(xml.contains("Figure 1: "));
        assert!(xml.contains("Figure 2: "));
        assert!(xml.contains("Table 1: "));
        // image placeholder + caption style + centered content
        assert!(xml.contains("[image: a.png]"));
        assert!(xml.contains("w:pStyle w:val=\"Caption\""));
        assert!(xml.contains("<w:jc w:val=\"center\"/>"));
        assert!(styles_xml().contains("w:styleId=\"Caption\""));
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
