//! Word field codes and bookmarks (`SEQ` / `REF` / `PAGEREF`) — a Rust port of
//! the Python `backend/fields.py`.
//!
//! These are the primitives that make numbering *live*: a complex field is a run
//! sequence `fldChar begin` → `instrText` (the code) → `fldChar separate` → a
//! cached result run → `fldChar end`. Word recomputes the result on field
//! refresh, so `\ref`/caption numbers auto-renumber. Bookmarks mark the targets
//! those fields point at; ids come from a per-document [`Bookmarks`] counter so
//! output stays deterministic.

use crate::ooxml::{escape, escape_text};

/// A monotonic, per-document bookmark-id source (reset per render for
/// deterministic output, like Python's `reset_bookmark_ids`).
#[derive(Default)]
pub struct Bookmarks {
    next: u32,
}

impl Bookmarks {
    /// Open a bookmark: returns `(<w:bookmarkStart …/>, id)`. Pair the id with
    /// [`Bookmarks::end`] once the bookmarked content is emitted.
    pub fn start(&mut self, name: &str, out: &mut String) -> u32 {
        let id = self.next;
        self.next += 1;
        out.push_str(&format!(
            "<w:bookmarkStart w:id=\"{id}\" w:name=\"{}\"/>",
            escape(name)
        ));
        id
    }

    pub fn end(&self, id: u32, out: &mut String) {
        out.push_str(&format!("<w:bookmarkEnd w:id=\"{id}\"/>"));
    }
}

/// Open a complex field: `fldChar begin` → `instrText` (code) → `fldChar
/// separate`. Follow with the result run(s), then [`field_close`].
pub fn field_open(code: &str, out: &mut String) {
    out.push_str("<w:r><w:fldChar w:fldCharType=\"begin\"/></w:r>");
    out.push_str("<w:r><w:instrText xml:space=\"preserve\">");
    out.push_str(&escape_text(code));
    out.push_str("</w:instrText></w:r>");
    out.push_str("<w:r><w:fldChar w:fldCharType=\"separate\"/></w:r>");
}

/// Close a complex field opened with [`field_open`] (`fldChar end`).
pub fn field_close(out: &mut String) {
    out.push_str("<w:r><w:fldChar w:fldCharType=\"end\"/></w:r>");
}

/// A complete complex field with a single cached result run. `code` is the
/// instruction (e.g. `SEQ Figure \* ARABIC`); `cached` is the placeholder shown
/// until Word refreshes fields.
pub fn field(code: &str, cached: &str, out: &mut String) {
    let shown = if cached.is_empty() { " " } else { cached };
    field_open(code, out);
    out.push_str("<w:r><w:t xml:space=\"preserve\">");
    out.push_str(&escape(shown));
    out.push_str("</w:t></w:r>");
    field_close(out);
}

/// A `SEQ <counter>` auto-number (the live figure/table/equation number).
pub fn seq_field(counter: &str, out: &mut String) {
    field(&format!("SEQ {counter} \\* ARABIC"), "1", out);
}

/// A `REF <bookmark>` field. `paragraph_number` uses `\r` (the target's list /
/// section number); otherwise `\h` hyperlinks to the bookmark.
pub fn ref_field(bookmark: &str, paragraph_number: bool, out: &mut String) {
    let switches = if paragraph_number { "\\r \\h" } else { "\\h" };
    field(&format!("REF {bookmark} {switches}"), "1", out);
}

/// A `PAGEREF <bookmark> \h` field (the page the bookmark is on).
pub fn pageref_field(bookmark: &str, out: &mut String) {
    field(&format!("PAGEREF {bookmark} \\h"), "1", out);
}

/// A `TOC` field (table of contents / list of figures/tables) with a cached
/// "update fields" hint.
pub fn toc_field(code: &str, out: &mut String) {
    field(
        code,
        "Right-click and choose \u{201c}Update Field\u{201d}.",
        out,
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn field_has_the_five_runs() {
        let mut s = String::new();
        field("SEQ Figure \\* ARABIC", "1", &mut s);
        assert!(s.contains("w:fldCharType=\"begin\""));
        assert!(
            s.contains("<w:instrText xml:space=\"preserve\">SEQ Figure \\* ARABIC</w:instrText>")
        );
        assert!(s.contains("w:fldCharType=\"separate\""));
        assert!(s.contains("w:fldCharType=\"end\""));
    }

    #[test]
    fn bookmarks_pair_ids_deterministically() {
        let mut bm = Bookmarks::default();
        let mut s = String::new();
        let id0 = bm.start("fig_a", &mut s);
        bm.end(id0, &mut s);
        let id1 = bm.start("fig_b", &mut s);
        bm.end(id1, &mut s);
        assert_eq!((id0, id1), (0, 1));
        assert!(s.contains("w:bookmarkStart w:id=\"0\" w:name=\"fig_a\""));
        assert!(s.contains("w:bookmarkEnd w:id=\"1\""));
    }

    #[test]
    fn ref_and_pageref_codes() {
        let mut s = String::new();
        ref_field("fig_a", false, &mut s);
        pageref_field("fig_a", &mut s);
        assert!(s.contains("REF fig_a \\h"));
        assert!(s.contains("PAGEREF fig_a \\h"));
    }
}
