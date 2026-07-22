//! OOXML (WordprocessingML) generation: IR -> the XML parts of a `.docx`.
//!
//! Emits `word/document.xml` (paragraphs, headings, styled runs, lists via
//! `numbering.xml`, quotes, structured OMML math via the `tex2word-math` crate,
//! `w:tbl` tables with spans/merges, figure/table floats with live `SEQ`-field
//! captions and embedded images, numbered sections, TOC fields, multi-column
//! section layout, cross-references as live `REF`/`PAGEREF`/`HYPERLINK` fields
//! with bookmarks, hyperlinked citations, and a bibliography) plus the package
//! parts (`[Content_Types].xml`, relationships, `styles.xml`, `numbering.xml`,
//! `word/media/*`, and `word/footnotes.xml`).

use std::collections::HashMap;
use std::path::Path;

use tex2word_ir::{
    Block, CiteMode, Document, EmphasisKind, Float, FloatKind, Inline, LabelInfo, RefKind,
    RefStyle, Table, TableAlign, Theorem, TocKind,
};

use crate::fields::{self, Bookmarks};
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

/// Mutable render state: media, drawing/bookmark ids, and the resolved label map
/// from the cross-reference pass. Figure/table numbers are live `SEQ` fields, so
/// no static counters are kept.
struct Ctx<'a> {
    drawing_id: u32,
    media: MediaRegistry<'a>,
    bookmarks: Bookmarks,
    /// Resolved `\label` → bookmark/counter map (from the cross-reference pass).
    labels: &'a HashMap<String, LabelInfo>,
    /// Collected `\footnote`s: `(id, content)` lifted into `footnotes.xml`.
    footnote_id: u32,
    footnotes: Vec<(u32, Vec<Inline>)>,
}

impl Ctx<'_> {
    /// The sanitized bookmark for a `\label` key, if it was resolved.
    fn bookmark_of(&self, label: &Option<String>) -> Option<String> {
        let key = label.as_ref()?;
        self.labels.get(key).map(|i| i.bookmark.clone())
    }
}

/// Escape XML text content / attribute values.
pub(crate) fn escape(s: &str) -> String {
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

/// Escape XML *text content* only (`&`/`<`/`>`); quotes stay literal. Used for
/// field-code `instrText`, where `HYPERLINK "url"` must keep its quotes.
pub(crate) fn escape_text(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
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
            Inline::Ref {
                key,
                kind,
                style,
                bookmark,
            } => render_ref(key, *kind, *style, bookmark, rp, out),
            Inline::Link {
                inlines,
                url,
                anchor,
            } => render_link(inlines, url, anchor, rp, ctx, out),
            Inline::Cite { keys, mode, .. } => render_cite(keys, *mode, rp, ctx, out),
            Inline::Footnote { inlines } => {
                // Assign the next id, collect the content for footnotes.xml, and
                // emit a superscript reference mark in the body.
                ctx.footnote_id += 1;
                let id = ctx.footnote_id;
                ctx.footnotes.push((id, inlines.clone()));
                out.push_str(&format!(
                    "<w:r><w:rPr><w:rStyle w:val=\"FootnoteReference\"/></w:rPr>\
                     <w:footnoteReference w:id=\"{id}\"/></w:r>"
                ));
            }
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

/// Render a cross-reference to a live `REF`/`PAGEREF` field (or the raw key if it
/// never resolved). `\eqref`/equation refs are parenthesized; section and
/// list-item refs use `\r` (the target's paragraph number). Cleveref-style type
/// prefixes are a Sprint-2 refinement.
fn render_ref(
    key: &str,
    kind: RefKind,
    style: RefStyle,
    bookmark: &Option<String>,
    rp: RunProps,
    out: &mut String,
) {
    let Some(bm) = bookmark else {
        render_run(key, rp, out); // unresolved -> literal key
        return;
    };
    // cleveref-style type prefix ("Figure ", "fig. ", …); \ref/\eqref stay bare.
    let prefix = ref_prefix(kind, style);
    if !prefix.is_empty() {
        render_run(prefix, rp, out);
    }
    match kind {
        RefKind::Page => fields::pageref_field(bm, out),
        RefKind::Equation => {
            render_run("(", rp, out);
            fields::ref_field(bm, false, out);
            render_run(")", rp, out);
        }
        RefKind::Section | RefKind::ListItem => fields::ref_field(bm, true, out),
        _ => fields::ref_field(bm, false, out),
    }
}

/// The cleveref-style type prefix for a `(kind, style)` pair (mirrors Python's
/// `_REF_NAMES`/`_REF_PREFIX`); `Plain` and unlisted kinds get no prefix.
fn ref_prefix(kind: RefKind, style: RefStyle) -> &'static str {
    use RefKind::{Equation, Figure, Section, Table, Theorem};
    use RefStyle::{Abbrev, Full};
    match (kind, style) {
        (Figure, Abbrev) => "fig. ",
        (Figure, Full) => "Figure ",
        (Table, Abbrev) => "tab. ",
        (Table, Full) => "Table ",
        (Section, Abbrev) => "sec. ",
        (Section, Full) => "Section ",
        (Equation, Abbrev) => "eq. ",
        (Equation, Full) => "Equation ",
        (Theorem, Abbrev) => "thm. ",
        (Theorem, Full) => "Theorem ",
        _ => "",
    }
}

/// Render a citation marker from a numeric `thebibliography`: each resolved key
/// becomes its reference number, hyperlinked to the reference bookmark;
/// `\citenum` drops the brackets. Unknown keys fall back to the raw key text
/// (the citation pass already warned).
fn render_cite(keys: &[String], mode: CiteMode, rp: RunProps, ctx: &mut Ctx, out: &mut String) {
    let resolved: Vec<(String, Option<String>)> = keys
        .iter()
        .map(|k| match ctx.labels.get(&format!("cite:{k}")) {
            Some(info) => (
                info.name.clone().unwrap_or_else(|| k.clone()),
                Some(info.bookmark.clone()),
            ),
            None => (k.clone(), None),
        })
        .collect();
    let bracketed = mode != CiteMode::Num;
    if bracketed {
        render_run("[", rp, out);
    }
    for (i, (num, bookmark)) in resolved.iter().enumerate() {
        if i > 0 {
            render_run(", ", rp, out);
        }
        match bookmark {
            Some(b) => {
                fields::field_open(&format!("HYPERLINK \\l \"{}\"", b.replace('"', "")), out);
                let mut rp2 = rp;
                rp2.underline = true;
                render_run(num, rp2, out);
                fields::field_close(out);
            }
            None => render_run(num, rp, out),
        }
    }
    if bracketed {
        render_run("]", rp, out);
    }
}

/// Render a hyperlink as a `HYPERLINK` field (`\l "anchor"` internal, or a URL),
/// with underlined children — no relationship part needed.
fn render_link(
    inlines: &[Inline],
    url: &str,
    anchor: &Option<String>,
    rp: RunProps,
    ctx: &mut Ctx,
    out: &mut String,
) {
    let instr = match anchor {
        Some(a) => format!("HYPERLINK \\l \"{}\"", a.replace('"', "")),
        None => format!("HYPERLINK \"{}\"", url.replace('"', "")),
    };
    fields::field_open(&instr, out);
    let mut rp2 = rp;
    rp2.underline = true;
    render_inlines(inlines, rp2, ctx, out);
    fields::field_close(out);
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
        Block::Heading {
            level,
            inlines,
            label,
            numbered,
        } => render_heading(*level, inlines, label, *numbered, ctx, out),
        Block::Paragraph { inlines } => render_paragraph(None, inlines, ctx, out),
        Block::MathBlock {
            latex,
            label,
            numbered,
        } => {
            // Numbered equations carry a right-tabbed live "(SEQ Equation)" number
            // in a bookmark (so \eqref points at it); plain \[…\] stays centered.
            if *numbered || label.is_some() {
                out.push_str(
                    "<w:p><w:pPr><w:tabs><w:tab w:val=\"right\" w:pos=\"9360\"/></w:tabs></w:pPr>",
                );
                render_math(latex, out);
                out.push_str("<w:r><w:tab/></w:r>");
                render_run("(", RunProps::default(), out);
                match ctx.bookmark_of(label) {
                    Some(name) => {
                        let id = ctx.bookmarks.start(&name, out);
                        fields::seq_field("Equation", out);
                        ctx.bookmarks.end(id, out);
                    }
                    None => fields::seq_field("Equation", out),
                }
                render_run(")", RunProps::default(), out);
                out.push_str("</w:p>");
            } else {
                out.push_str("<w:p><w:pPr><w:jc w:val=\"center\"/></w:pPr>");
                render_math(latex, out);
                out.push_str("</w:p>");
            }
        }
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
        Block::TableOfContents(kind) => render_toc(*kind, out),
        Block::Bibliography { entries } => render_bibliography(entries, ctx, out),
        Block::Theorem(theorem) => render_theorem(theorem, ctx, out),
    }
}

/// Render a theorem-like environment: a bold "Kind N (Title). " lead-in (with a
/// live `SEQ Theorem` number in a bookmark when numbered/labelled), then the
/// body — statement kinds italic, `proof` upright and closed with a ∎. The
/// lead-in is merged into the first body paragraph so it reads inline.
fn render_theorem(t: &Theorem, ctx: &mut Ctx, out: &mut String) {
    let italic_body = matches!(
        t.kind.as_str(),
        "Theorem" | "Lemma" | "Proposition" | "Corollary"
    );
    let is_proof = t.kind == "Proof";
    let body_rp = RunProps {
        italic: italic_body,
        ..Default::default()
    };
    let head_rp = RunProps {
        bold: !is_proof,
        italic: is_proof,
        ..Default::default()
    };

    out.push_str("<w:p>");
    // Lead-in: "Proof." (italic) or "Kind [N] [(Title)]." (bold).
    if is_proof {
        render_run("Proof. ", head_rp, out);
    } else {
        render_run(&t.kind, head_rp, out);
        if let Some(counter) = &t.counter {
            render_run(" ", head_rp, out);
            match ctx.bookmark_of(&t.label) {
                Some(name) => {
                    let id = ctx.bookmarks.start(&name, out);
                    fields::seq_field(counter, out);
                    ctx.bookmarks.end(id, out);
                }
                None => fields::seq_field(counter, out),
            }
        }
        if let Some(title) = &t.title {
            render_run(" (", head_rp, out);
            render_inlines(title, head_rp, ctx, out);
            render_run(")", head_rp, out);
        }
        render_run(". ", head_rp, out);
    }
    // Merge the first paragraph into the lead-in; render the rest as blocks.
    let mut rest = t.blocks.as_slice();
    if let Some((Block::Paragraph { inlines }, tail)) = t.blocks.split_first() {
        render_inlines(inlines, body_rp, ctx, out);
        rest = tail;
    }
    if is_proof && rest.is_empty() {
        render_run(" \u{220E}", RunProps::default(), out); // QED on a one-para proof
    }
    out.push_str("</w:p>");
    for b in rest {
        render_block(b, ctx, out);
    }
}

/// Render a bibliography: a "References" heading + one numbered paragraph per
/// entry. (Bookmarks + `\cite` hyperlinking are wired by the citation pass.)
fn render_bibliography(entries: &[tex2word_ir::BibEntry], ctx: &mut Ctx, out: &mut String) {
    render_paragraph(
        Some("Heading1"),
        &[Inline::Text("References".into())],
        ctx,
        out,
    );
    for (idx, e) in entries.iter().enumerate() {
        let label = e.label.clone().unwrap_or_else(|| (idx + 1).to_string());
        out.push_str("<w:p><w:pPr><w:pStyle w:val=\"Bibliography\"/></w:pPr>");
        match ctx.bookmark_of(&Some(format!("cite:{}", e.key))) {
            Some(name) => {
                let id = ctx.bookmarks.start(&name, out);
                render_run(&format!("[{label}]\t"), RunProps::default(), out);
                ctx.bookmarks.end(id, out);
            }
            None => render_run(&format!("[{label}]\t"), RunProps::default(), out),
        }
        render_inlines(&e.inlines, RunProps::default(), ctx, out);
        out.push_str("</w:p>");
    }
}

/// Render a heading paragraph: `HeadingN` style, auto-numbering for the numbered
/// forms (levels 1–4, via the multilevel list `numId` 3), and a bookmark around
/// the text when the heading is labelled (so `REF \r` can cite its number).
fn render_heading(
    level: u8,
    inlines: &[Inline],
    label: &Option<String>,
    numbered: bool,
    ctx: &mut Ctx,
    out: &mut String,
) {
    let style = format!("Heading{}", level.clamp(1, 9));
    out.push_str(&format!("<w:p><w:pPr><w:pStyle w:val=\"{style}\"/>"));
    if numbered && (1..=4).contains(&level) {
        out.push_str(&format!(
            "<w:numPr><w:ilvl w:val=\"{}\"/><w:numId w:val=\"3\"/></w:numPr>",
            level - 1
        ));
    }
    out.push_str("</w:pPr>");
    match ctx.bookmark_of(label) {
        Some(name) => {
            let id = ctx.bookmarks.start(&name, out);
            render_inlines(inlines, RunProps::default(), ctx, out);
            ctx.bookmarks.end(id, out);
        }
        None => render_inlines(inlines, RunProps::default(), ctx, out),
    }
    out.push_str("</w:p>");
}

/// Render a `\tableofcontents`/`\listof*` as a heading + a live `TOC` field.
fn render_toc(kind: TocKind, out: &mut String) {
    let (title, code) = match kind {
        TocKind::Contents => ("Contents", "TOC \\o \"1-3\" \\h \\z \\u"),
        TocKind::Figures => ("List of Figures", "TOC \\h \\z \\c \"Figure\""),
        TocKind::Tables => ("List of Tables", "TOC \\h \\z \\c \"Table\""),
    };
    out.push_str("<w:p><w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr>");
    render_run(title, RunProps::default(), out);
    out.push_str("</w:p><w:p>");
    fields::toc_field(code, out);
    out.push_str("</w:p>");
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
        let counter = match float.kind {
            FloatKind::Figure => "Figure",
            FloatKind::Table => "Table",
        };
        out.push_str("<w:p><w:pPr><w:pStyle w:val=\"Caption\"/>");
        if float.centered {
            out.push_str("<w:jc w:val=\"center\"/>");
        }
        out.push_str("</w:pPr>");
        let bold = RunProps {
            bold: true,
            ..Default::default()
        };
        render_run(&format!("{counter} "), bold, out);
        // the number: a live SEQ field, wrapped in the float's bookmark if labelled
        match ctx.bookmark_of(&float.label) {
            Some(name) => {
                let id = ctx.bookmarks.start(&name, out);
                fields::seq_field(counter, out);
                ctx.bookmarks.end(id, out);
            }
            None => fields::seq_field(counter, out),
        }
        render_run(": ", bold, out);
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
    // CT_TblPr child order: tblStyle, tblW, jc, tblBorders, … (tblW before jc).
    out.push_str("<w:tbl><w:tblPr><w:tblStyle w:val=\"TableGrid\"/>");
    out.push_str("<w:tblW w:w=\"0\" w:type=\"auto\"/>");
    if center {
        out.push_str("<w:jc w:val=\"center\"/>");
    }
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
/// A `w:sectPr` for a column region: `continuous` marks a mid-page section
/// break; `cols > 1` adds a `w:cols` (a single-column section omits it, the
/// schema default).
fn sect_pr(cols: usize, continuous: bool) -> String {
    let mut s = String::from("<w:sectPr>");
    if continuous {
        s.push_str("<w:type w:val=\"continuous\"/>");
    }
    s.push_str("<w:pgSz w:w=\"12240\" w:h=\"15840\"/>");
    s.push_str(
        "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" \
         w:header=\"720\" w:footer=\"720\"/>",
    );
    if cols > 1 {
        s.push_str(&format!("<w:cols w:num=\"{cols}\" w:space=\"720\"/>"));
    }
    s.push_str("</w:sectPr>");
    s
}

/// Between regions of differing column counts, emit an empty paragraph whose
/// `pPr` carries the *closing* region's continuous `sectPr`. Updates `prev`.
fn region_break(prev: &mut Option<usize>, cols: usize, body: &mut String) {
    if let Some(p) = *prev {
        if p != cols {
            body.push_str("<w:p><w:pPr>");
            body.push_str(&sect_pr(p, true));
            body.push_str("</w:pPr></w:p>");
        }
    }
    *prev = Some(cols);
}

pub fn build_package(doc: &Document, base_dir: &Path) -> Package {
    let mut ctx = Ctx {
        drawing_id: 0,
        media: MediaRegistry::new(base_dir),
        bookmarks: Bookmarks::default(),
        labels: &doc.labels,
        footnote_id: 0,
        footnotes: Vec::new(),
    };
    // Emit the body as column "regions": the title block and any spanning
    // `figure*`/`table*` are full-width (1 col); the rest flows in `n` columns.
    // Continuous section breaks (carrying the closed region's sectPr) separate
    // regions with differing column counts.
    let n = doc.columns.max(1);
    let mut body = String::new();
    let mut prev: Option<usize> = None;
    let has_title = doc.title.is_some() || !doc.authors.is_empty() || doc.date.is_some();
    if has_title {
        region_break(&mut prev, if n > 1 { 1 } else { n }, &mut body);
        if let Some(title) = &doc.title {
            render_paragraph(Some("Title"), title, &mut ctx, &mut body);
        }
        for author in &doc.authors {
            render_paragraph(Some("Subtitle"), author, &mut ctx, &mut body);
        }
        if let Some(date) = &doc.date {
            render_paragraph(Some("Subtitle"), date, &mut ctx, &mut body);
        }
    }
    for block in &doc.blocks {
        let spanning = matches!(block, Block::Float(f) if f.spanning);
        let cols = if n > 1 && spanning { 1 } else { n };
        region_break(&mut prev, cols, &mut body);
        render_block(block, &mut ctx, &mut body);
    }
    // The final region's sectPr closes the body.
    body.push_str(&sect_pr(prev.unwrap_or(n), false));
    let document_xml = format!(
        concat!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
            "<w:document xmlns:w=\"{w}\" xmlns:m=\"{m}\" xmlns:r=\"{r}\" ",
            "xmlns:wp=\"{wp}\" xmlns:a=\"{a}\" xmlns:pic=\"{pic}\"><w:body>{body}",
            "</w:body></w:document>"
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
    let mut extra_rels = String::new();
    let mut exts: Vec<String> = Vec::new();
    let mut media: Vec<MediaPart> = Vec::new();
    for m in &ctx.media.items {
        extra_rels.push_str(&format!(
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

    // Footnotes: render the collected notes into word/footnotes.xml + wire the
    // relationship and content type.
    let has_footnotes = !ctx.footnotes.is_empty();
    if has_footnotes {
        let footnotes_xml = render_footnotes_xml(&mut ctx);
        extra_rels.push_str(&format!(
            "<Relationship Id=\"rIdFootnotes\" Type=\"{R_NS}/footnotes\" Target=\"footnotes.xml\"/>"
        ));
        media.push(MediaPart {
            part_name: "word/footnotes.xml".into(),
            data: footnotes_xml.into_bytes(),
        });
    }

    Package {
        document_xml,
        content_types_xml: content_types_xml(&exts, has_footnotes),
        doc_rels_xml: doc_rels_xml(&extra_rels),
        media,
    }
}

/// Render `word/footnotes.xml`: the mandatory separator/continuationSeparator
/// pair (ids −1/0) then one `w:footnote` per collected note. Notes discovered
/// while rendering a note's own content are drained in a follow-up round.
fn render_footnotes_xml(ctx: &mut Ctx) -> String {
    let mut s = String::from(concat!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n",
        "<w:footnotes xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" ",
        "xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\">",
        "<w:footnote w:type=\"separator\" w:id=\"-1\"><w:p><w:pPr>",
        "<w:spacing w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/></w:pPr>",
        "<w:r><w:separator/></w:r></w:p></w:footnote>",
        "<w:footnote w:type=\"continuationSeparator\" w:id=\"0\"><w:p><w:pPr>",
        "<w:spacing w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/></w:pPr>",
        "<w:r><w:continuationSeparator/></w:r></w:p></w:footnote>",
    ));
    let mut pending = std::mem::take(&mut ctx.footnotes);
    while !pending.is_empty() {
        for (id, inlines) in &pending {
            s.push_str(&format!("<w:footnote w:id=\"{id}\">"));
            s.push_str("<w:p><w:pPr><w:pStyle w:val=\"FootnoteText\"/></w:pPr>");
            s.push_str(
                "<w:r><w:rPr><w:rStyle w:val=\"FootnoteReference\"/></w:rPr><w:footnoteRef/></w:r>",
            );
            render_run(" ", RunProps::default(), &mut s);
            render_inlines(inlines, RunProps::default(), ctx, &mut s);
            s.push_str("</w:p></w:footnote>");
        }
        pending = std::mem::take(&mut ctx.footnotes); // notes nested inside notes
    }
    s.push_str("</w:footnotes>");
    s
}

/// The `[Content_Types].xml` part, with a `Default` for each embedded image ext
/// and (when present) the `footnotes.xml` override.
fn content_types_xml(image_exts: &[String], footnotes: bool) -> String {
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
    ));
    if footnotes {
        s.push_str("<Override PartName=\"/word/footnotes.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml\"/>");
    }
    s.push_str("</Types>");
    s
}

/// The `word/_rels/document.xml.rels` part: styles + numbering + image/footnote
/// relationships.
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
    // abstractNum 2 = multilevel heading numbering (1, 1.1, 1.1.1, 1.1.1.1).
    "<w:abstractNum w:abstractNumId=\"2\"><w:multiLevelType w:val=\"multilevel\"/>",
    "<w:lvl w:ilvl=\"0\"><w:start w:val=\"1\"/><w:numFmt w:val=\"decimal\"/>",
    "<w:lvlText w:val=\"%1\"/><w:lvlJc w:val=\"left\"/>",
    "<w:pPr><w:ind w:left=\"0\" w:firstLine=\"0\"/></w:pPr></w:lvl>",
    "<w:lvl w:ilvl=\"1\"><w:start w:val=\"1\"/><w:numFmt w:val=\"decimal\"/>",
    "<w:lvlText w:val=\"%1.%2\"/><w:lvlJc w:val=\"left\"/>",
    "<w:pPr><w:ind w:left=\"0\" w:firstLine=\"0\"/></w:pPr></w:lvl>",
    "<w:lvl w:ilvl=\"2\"><w:start w:val=\"1\"/><w:numFmt w:val=\"decimal\"/>",
    "<w:lvlText w:val=\"%1.%2.%3\"/><w:lvlJc w:val=\"left\"/>",
    "<w:pPr><w:ind w:left=\"0\" w:firstLine=\"0\"/></w:pPr></w:lvl>",
    "<w:lvl w:ilvl=\"3\"><w:start w:val=\"1\"/><w:numFmt w:val=\"decimal\"/>",
    "<w:lvlText w:val=\"%1.%2.%3.%4\"/><w:lvlJc w:val=\"left\"/>",
    "<w:pPr><w:ind w:left=\"0\" w:firstLine=\"0\"/></w:pPr></w:lvl></w:abstractNum>",
    "<w:num w:numId=\"1\"><w:abstractNumId w:val=\"0\"/></w:num>",
    "<w:num w:numId=\"2\"><w:abstractNumId w:val=\"1\"/></w:num>",
    "<w:num w:numId=\"3\"><w:abstractNumId w:val=\"2\"/></w:num>",
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
        // Bibliography (reference list): hanging indent.
        "<w:style w:type=\"paragraph\" w:styleId=\"Bibliography\"><w:name w:val=\"Bibliography\"/>",
        "<w:basedOn w:val=\"Normal\"/><w:next w:val=\"Normal\"/>",
        "<w:pPr><w:ind w:left=\"480\" w:hanging=\"480\"/></w:pPr></w:style>",
        // Footnote reference mark (superscript) + footnote text (smaller).
        "<w:style w:type=\"character\" w:styleId=\"FootnoteReference\">",
        "<w:name w:val=\"footnote reference\"/><w:rPr><w:vertAlign w:val=\"superscript\"/></w:rPr></w:style>",
        "<w:style w:type=\"paragraph\" w:styleId=\"FootnoteText\"><w:name w:val=\"footnote text\"/>",
        "<w:basedOn w:val=\"Normal\"/><w:rPr><w:sz w:val=\"20\"/></w:rPr></w:style>",
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
                label: None,
                spanning: false,
            })
        };
        let tbl = Block::Float(Float {
            kind: FloatKind::Table,
            content: vec![],
            caption: Some(vec![Inline::Text("T".into())]),
            centered: false,
            label: None,
            spanning: false,
        });
        let doc = Document {
            blocks: vec![fig("a"), tbl, fig("b")],
            ..Default::default()
        };
        let xml = document_xml(&doc);
        // live SEQ fields (Word keeps Figure/Table series independent by name)
        assert_eq!(xml.matches("SEQ Figure \\* ARABIC").count(), 2);
        assert_eq!(xml.matches("SEQ Table \\* ARABIC").count(), 1);
        assert!(xml.contains(">Figure </w:t>")); // the "Figure " prefix run
        assert!(xml.contains(">Table </w:t>"));
        // image placeholder + caption style + centered content
        assert!(xml.contains("[image: a.png]"));
        assert!(xml.contains("w:pStyle w:val=\"Caption\""));
        assert!(xml.contains("<w:jc w:val=\"center\"/>"));
        assert!(styles_xml().contains("w:styleId=\"Caption\""));
    }

    #[test]
    fn numbered_headings_toc_and_cleveref_prefix() {
        use std::collections::HashMap;
        let mut labels = HashMap::new();
        labels.insert(
            "fig:a".to_string(),
            LabelInfo {
                kind: RefKind::Figure,
                counter_name: "Figure".into(),
                bookmark: "fig_a".into(),
                name: None,
            },
        );
        let doc = Document {
            labels,
            blocks: vec![
                Block::TableOfContents(TocKind::Contents),
                Block::Heading {
                    level: 1,
                    inlines: vec![Inline::Text("Intro".into())],
                    label: None,
                    numbered: true,
                },
                Block::Heading {
                    level: 1,
                    inlines: vec![Inline::Text("Unnum".into())],
                    label: None,
                    numbered: false,
                },
                Block::Paragraph {
                    inlines: vec![Inline::Ref {
                        key: "fig:a".into(),
                        kind: RefKind::Figure,
                        style: RefStyle::Full, // \Cref -> "Figure " prefix
                        bookmark: Some("fig_a".into()),
                    }],
                },
            ],
            ..Default::default()
        };
        let xml = document_xml(&doc);
        // numbered heading carries numPr (numId 3); the starred one does not
        assert_eq!(xml.matches("<w:numId w:val=\"3\"/>").count(), 1);
        // TOC heading + field
        assert!(xml.contains(">Contents</w:t>"));
        assert!(xml.contains("TOC \\o \"1-3\" \\h \\z \\u"));
        // cleveref \Cref prefix precedes the REF field
        assert!(xml.contains(">Figure </w:t>"));
        assert!(xml.contains("REF fig_a \\h"));
        // heading numbering definition exists
        assert!(NUMBERING_XML.contains("w:numId=\"3\""));
    }

    #[test]
    fn twocolumn_layout_with_spanning_float() {
        let doc = Document {
            columns: 2,
            blocks: vec![
                Block::Paragraph {
                    inlines: vec![Inline::Text("body".into())],
                },
                Block::Float(Float {
                    kind: FloatKind::Figure,
                    content: vec![],
                    caption: Some(vec![Inline::Text("C".into())]),
                    centered: false,
                    label: None,
                    spanning: true,
                }),
                Block::Paragraph {
                    inlines: vec![Inline::Text("more".into())],
                },
            ],
            ..Default::default()
        };
        let xml = document_xml(&doc);
        // two 2-column regions (before/after the float) + one full-width region
        assert_eq!(xml.matches("<w:cols w:num=\"2\"").count(), 2);
        // continuous section breaks bracket the spanning float
        assert_eq!(xml.matches("<w:type w:val=\"continuous\"/>").count(), 2);
        // 2 continuous-break sectPrs + the final body sectPr
        assert_eq!(xml.matches("<w:sectPr>").count(), 3);
    }

    #[test]
    fn single_column_has_no_cols_element() {
        let doc = Document {
            columns: 1,
            blocks: vec![Block::Paragraph {
                inlines: vec![Inline::Text("x".into())],
            }],
            ..Default::default()
        };
        let xml = document_xml(&doc);
        assert!(!xml.contains("<w:cols"));
        assert_eq!(xml.matches("<w:sectPr>").count(), 1); // just the final one
    }

    #[test]
    fn cites_resolve_and_footnotes_lift_to_part() {
        use std::collections::HashMap;
        use tex2word_ir::BibEntry;
        let mut labels = HashMap::new();
        labels.insert(
            "cite:a".to_string(),
            LabelInfo {
                kind: RefKind::Generic,
                counter_name: String::new(),
                bookmark: "cite_a".into(),
                name: Some("1".into()),
            },
        );
        let doc = Document {
            labels,
            blocks: vec![
                Block::Paragraph {
                    inlines: vec![
                        Inline::Cite {
                            keys: vec!["a".into(), "missing".into()],
                            mode: CiteMode::Paren,
                            rendered: None,
                        },
                        Inline::Footnote {
                            inlines: vec![Inline::Text("a note".into())],
                        },
                    ],
                },
                Block::Bibliography {
                    entries: vec![BibEntry {
                        key: "a".into(),
                        label: None,
                        inlines: vec![Inline::Text("Author. Title. 2020.".into())],
                    }],
                },
            ],
            ..Default::default()
        };
        // package (not just document_xml) so footnotes.xml + rels are built
        let pkg = build_package(&doc, Path::new("."));
        let d = &pkg.document_xml;
        // resolved cite "a" hyperlinks to cite_a and shows its number "1"
        assert!(d.contains("HYPERLINK \\l \"cite_a\""));
        assert!(d.contains(">1</w:t>"));
        // footnote reference mark in the body
        assert!(d.contains("<w:footnoteReference w:id=\"1\"/>"));
        assert!(d.contains("w:val=\"FootnoteReference\""));
        // References heading + hanging-indent bibliography paragraph, bookmarked
        assert!(d.contains(">References</w:t>"));
        assert!(d.contains("w:pStyle w:val=\"Bibliography\""));
        assert!(d.contains("w:name=\"cite_a\""));
        // footnotes.xml part exists with the note content + separators
        let fn_part = pkg
            .media
            .iter()
            .find(|m| m.part_name == "word/footnotes.xml")
            .expect("footnotes.xml");
        let f = String::from_utf8_lossy(&fn_part.data);
        assert!(f.contains("w:type=\"separator\"") && f.contains("<w:footnoteRef/>"));
        assert!(f.contains("a note"));
        // relationship + content type wired
        assert!(pkg.doc_rels_xml.contains("Target=\"footnotes.xml\""));
        assert!(pkg.content_types_xml.contains("/word/footnotes.xml"));
    }

    #[test]
    fn theorem_renders_seq_and_proof_qed() {
        use std::collections::HashMap;
        let mut labels = HashMap::new();
        labels.insert(
            "thm:a".to_string(),
            LabelInfo {
                kind: RefKind::Theorem,
                counter_name: "Theorem".into(),
                bookmark: "thm_a".into(),
                name: Some("Pythagoras".into()),
            },
        );
        let thm = Block::Theorem(Theorem {
            kind: "Theorem".into(),
            blocks: vec![Block::Paragraph {
                inlines: vec![Inline::Text("Statement.".into())],
            }],
            title: Some(vec![Inline::Text("Pythagoras".into())]),
            label: Some("thm:a".into()),
            counter: Some("Theorem".into()),
        });
        let proof = Block::Theorem(Theorem {
            kind: "Proof".into(),
            blocks: vec![Block::Paragraph {
                inlines: vec![Inline::Text("Obvious.".into())],
            }],
            title: None,
            label: None,
            counter: None,
        });
        let doc = Document {
            labels,
            blocks: vec![thm, proof],
            ..Default::default()
        };
        let xml = document_xml(&doc);
        // numbered theorem: live SEQ Theorem inside its bookmark + the title
        assert!(xml.contains("SEQ Theorem \\* ARABIC"));
        assert!(xml.contains("w:name=\"thm_a\""));
        assert!(xml.contains(">Pythagoras</w:t>"));
        // proof: italic "Proof. " lead-in + a QED mark, no SEQ
        assert!(xml.contains(">Proof. </w:t>"));
        assert!(xml.contains('\u{220E}'));
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
