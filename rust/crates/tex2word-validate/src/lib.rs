//! Pragmatic structural validation of a tex2word `.docx` — a Rust port of the
//! Python `tex2word.validate`.
//!
//! Full ECMA-376 XSD validation is impractical offline; this instead enforces
//! the invariants that catch *our* bugs:
//!
//! 1. **OPC structure** — the package opens, the required parts exist, every XML
//!    part is well-formed, every part has a declared content type, and every
//!    relationship target resolves to a real part.
//! 2. **Content model** — the child ordering of the property complex types we
//!    emit (`w:rPr`/`w:pPr`/`w:tblPr`/`w:trPr`/`w:tcPr` follow the schema
//!    sequence — the exact defect class Word silently repairs), plus field and
//!    bookmark pairing.
//!
//! The reader handles the STORE (uncompressed) entries tex2word writes; a
//! DEFLATE-compressed entry (from a foreign `.docx`) is enumerated but its
//! content is not inspected.

mod zipread;

use std::collections::HashSet;

const CT_PART: &str = "[Content_Types].xml";
const REQUIRED: &[&str] = &[
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
    "word/styles.xml",
];

/// Validate a `.docx` byte buffer. Returns a list of human-readable violations
/// (empty ⇒ the package passes the structural checks).
pub fn validate_docx(bytes: &[u8]) -> Vec<String> {
    let mut out = Vec::new();
    let entries = match zipread::read(bytes) {
        Ok(e) => e,
        Err(e) => return vec![format!("not a readable ZIP/OPC package: {e}")],
    };
    let names: HashSet<&str> = entries.iter().map(|e| e.name.as_str()).collect();

    for req in REQUIRED {
        if !names.contains(req) {
            out.push(format!("missing required part '{req}'"));
        }
    }

    // Well-formedness of every XML/rels part we can read.
    for e in &entries {
        if !(e.name.ends_with(".xml") || e.name.ends_with(".rels")) {
            continue;
        }
        if let Some(data) = &e.data {
            if let Some(err) = wellformed(&String::from_utf8_lossy(data)) {
                out.push(format!("{}: not well-formed: {err}", e.name));
            }
        }
    }

    check_content_types(&entries, &names, &mut out);
    check_relationships(&entries, &names, &mut out);

    // Content-model checks on the main document part.
    if let Some(doc) = entries
        .iter()
        .find(|e| e.name == "word/document.xml")
        .and_then(|e| e.data.as_ref())
    {
        let xml = String::from_utf8_lossy(doc);
        check_child_order(&xml, &mut out);
        check_fields_and_bookmarks(&xml, &mut out);
    }
    out
}

/// A minimal XML well-formedness check: element open/close nesting must balance.
/// (Skips PIs/comments/doctype; not a full parser, but catches the realistic
/// breakage — mismatched or unclosed tags.) Returns `Some(error)` if malformed.
fn wellformed(xml: &str) -> Option<String> {
    let mut stack: Vec<String> = Vec::new();
    let mut rest = xml;
    while let Some(lt) = rest.find('<') {
        rest = &rest[lt..];
        if let Some(r) = rest.strip_prefix("<?") {
            let end = r.find("?>")?;
            rest = &r[end + 2..];
            continue;
        }
        if let Some(r) = rest.strip_prefix("<!--") {
            let end = r.find("-->")?;
            rest = &r[end + 3..];
            continue;
        }
        if rest.starts_with("<!") {
            let end = rest.find('>')?;
            rest = &rest[end + 1..];
            continue;
        }
        let end = rest.find('>')?;
        let inner = &rest[1..end];
        let self_closing = inner.ends_with('/');
        let inner = inner.trim_end_matches('/').trim();
        if let Some(close) = inner.strip_prefix('/') {
            let name = close.split_whitespace().next().unwrap_or("");
            match stack.pop() {
                Some(top) if top == name => {}
                Some(top) => return Some(format!("</{name}> closes <{top}>")),
                None => return Some(format!("stray close </{name}>")),
            }
        } else if !self_closing {
            let name = inner
                .split(|c: char| c.is_whitespace())
                .next()
                .unwrap_or("");
            stack.push(name.to_string());
        }
        rest = &rest[end + 1..];
    }
    stack.pop().map(|top| format!("unclosed element <{top}>"))
}

/// Every part must have a declared content type (a `Default` for its extension
/// or an `Override` for its full part name).
fn check_content_types(entries: &[zipread::Entry], names: &HashSet<&str>, out: &mut Vec<String>) {
    let Some(ct) = entries
        .iter()
        .find(|e| e.name == CT_PART)
        .and_then(|e| e.data.as_ref())
    else {
        return; // the missing-part check already reported it
    };
    let ct = String::from_utf8_lossy(ct);
    let defaults: HashSet<String> = attr_values(&ct, "Default", "Extension")
        .into_iter()
        .map(|s| s.to_ascii_lowercase())
        .collect();
    let overrides: HashSet<String> = attr_values(&ct, "Override", "PartName")
        .into_iter()
        .collect();
    for name in names {
        if *name == CT_PART || name.ends_with('/') {
            continue;
        }
        let ext = name.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
        let part = format!("/{name}");
        if !defaults.contains(&ext) && !overrides.contains(&part) {
            out.push(format!("part '{name}' has no declared content type"));
        }
    }
}

/// Every internal relationship `Target` must resolve to a real part.
fn check_relationships(entries: &[zipread::Entry], names: &HashSet<&str>, out: &mut Vec<String>) {
    for e in entries {
        if !e.name.ends_with(".rels") {
            continue;
        }
        let Some(data) = e.data.as_ref() else {
            continue;
        };
        let text = String::from_utf8_lossy(data);
        // rels at "A/_rels/B.rels" resolve targets relative to "A/".
        let base = e
            .name
            .rsplit_once("_rels/")
            .map(|(dir, _)| dir.to_string())
            .unwrap_or_default();
        // Walk each <Relationship .../> and check Target unless it's External.
        for tag in element_tags(&text, "Relationship") {
            if attr(&tag, "TargetMode").as_deref() == Some("External") {
                continue;
            }
            let Some(target) = attr(&tag, "Target") else {
                continue;
            };
            let resolved = normalize_join(&base, &target);
            if !names.contains(resolved.as_str()) {
                out.push(format!(
                    "{}: relationship target '{target}' → '{resolved}' does not exist",
                    e.name
                ));
            }
        }
    }
}

/// The ECMA-376 child-order sequences for the property elements we emit. A
/// parent's direct children must appear as a subsequence of this order.
const CHILD_ORDER: &[(&str, &[&str])] = &[
    (
        "w:rPr",
        &[
            "rStyle",
            "rFonts",
            "b",
            "bCs",
            "i",
            "iCs",
            "caps",
            "smallCaps",
            "strike",
            "dstrike",
            "color",
            "spacing",
            "w",
            "position",
            "sz",
            "szCs",
            "highlight",
            "u",
            "vertAlign",
            "rtl",
            "lang",
        ],
    ),
    (
        "w:pPr",
        &[
            "pStyle",
            "keepNext",
            "keepLines",
            "numPr",
            "tabs",
            "spacing",
            "ind",
            "jc",
            "sectPr",
            "rPr",
        ],
    ),
    (
        "w:tblPr",
        &["tblStyle", "tblW", "jc", "tblBorders", "tblLook"],
    ),
    ("w:trPr", &["tblHeader"]),
    ("w:tcPr", &["tcW", "gridSpan", "vMerge"]),
];

fn check_child_order(xml: &str, out: &mut Vec<String>) {
    for (parent, order) in CHILD_ORDER {
        for children in direct_children_of(xml, parent) {
            let mut last = 0usize;
            for child in &children {
                match order.iter().position(|o| o == child) {
                    Some(pos) if pos >= last => last = pos,
                    Some(pos) => out.push(format!(
                        "{parent}: child <w:{child}> is out of schema order (after position {last}, expected ≥ it; got {pos})"
                    )),
                    None => {} // an element we don't constrain — no ordering claim
                }
            }
        }
    }
}

/// `fldChar` begin/end must balance; every `bookmarkStart` id needs a `bookmarkEnd`.
fn check_fields_and_bookmarks(xml: &str, out: &mut Vec<String>) {
    let begins = xml.matches("w:fldCharType=\"begin\"").count();
    let ends = xml.matches("w:fldCharType=\"end\"").count();
    if begins != ends {
        out.push(format!(
            "unbalanced complex fields: {begins} begin vs {ends} end"
        ));
    }
    let starts: HashSet<String> = element_tags(xml, "w:bookmarkStart")
        .iter()
        .filter_map(|t| attr(t, "w:id"))
        .collect();
    let ends_ids: HashSet<String> = element_tags(xml, "w:bookmarkEnd")
        .iter()
        .filter_map(|t| attr(t, "w:id"))
        .collect();
    for id in starts.difference(&ends_ids) {
        out.push(format!("bookmarkStart id={id} has no matching bookmarkEnd"));
    }
    for id in ends_ids.difference(&starts) {
        out.push(format!("bookmarkEnd id={id} has no matching bookmarkStart"));
    }
}

// ---- small XML helpers (string-level; the parts are our own emitted XML) ---- #

/// The full text of each `<tag …>` (attributes included), self-closing or open.
fn element_tags(xml: &str, tag: &str) -> Vec<String> {
    let mut out = Vec::new();
    let open = format!("<{tag}");
    let mut rest = xml;
    while let Some(p) = rest.find(&open) {
        let after = &rest[p + open.len()..];
        // the char after the name must be whitespace, '>' or '/'
        if !after
            .chars()
            .next()
            .is_some_and(|c| c.is_whitespace() || c == '>' || c == '/')
        {
            rest = after;
            continue;
        }
        let Some(end) = after.find('>') else { break };
        out.push(format!("<{tag}{}", &after[..end + 1]));
        rest = &after[end + 1..];
    }
    out
}

/// A single attribute's value from a tag string.
fn attr(tag: &str, name: &str) -> Option<String> {
    let key = format!("{name}=\"");
    let start = tag.find(&key)? + key.len();
    let end = tag[start..].find('"')? + start;
    Some(tag[start..end].to_string())
}

/// All values of `attr` across every `<element …>` occurrence.
fn attr_values(xml: &str, element: &str, attr_name: &str) -> Vec<String> {
    element_tags(xml, element)
        .iter()
        .filter_map(|t| attr(t, attr_name))
        .collect()
}

/// The ordered direct-child local names of every `<parent>…</parent>` block.
fn direct_children_of(xml: &str, parent: &str) -> Vec<Vec<String>> {
    let open = format!("<{parent}>");
    let open_attr = format!("<{parent} ");
    let close = format!("</{parent}>");
    let mut blocks = Vec::new();
    let mut rest = xml;
    loop {
        // find the next opening tag of `parent` (with or without attributes)
        let (pos, taglen) = match (rest.find(&open), rest.find(&open_attr)) {
            (Some(a), Some(b)) if a <= b => (a, tag_len(&rest[a..])),
            (Some(a), None) => (a, tag_len(&rest[a..])),
            (_, Some(b)) => (b, tag_len(&rest[b..])),
            (None, None) => break,
        };
        let body_start = pos + taglen;
        let mut depth = 1usize;
        let mut i = body_start;
        let mut children = Vec::new();
        let bytes = rest.as_bytes();
        while i < rest.len() {
            if bytes[i] != b'<' {
                i += 1;
                continue;
            }
            let tail = &rest[i..];
            if tail.starts_with(&close) {
                depth -= 1;
                if depth == 0 {
                    break;
                }
                i += close.len();
                continue;
            }
            let end = match tail.find('>') {
                Some(k) => k,
                None => break,
            };
            let inner = &tail[1..end];
            if inner.starts_with('/') {
                depth -= 1; // a nested close tag of some other element
            } else {
                let self_closing = inner.ends_with('/');
                let name = local_name(inner.trim_end_matches('/').trim());
                if depth == 1 {
                    children.push(name);
                }
                if !self_closing {
                    depth += 1;
                }
            }
            i += end + 1;
        }
        blocks.push(children);
        rest = &rest[body_start..];
    }
    blocks
}

fn tag_len(s: &str) -> usize {
    s.find('>').map(|k| k + 1).unwrap_or(s.len())
}

/// `w:pStyle` → `pStyle` (strip the namespace prefix).
fn local_name(tag_inner: &str) -> String {
    let name = tag_inner
        .split(|c: char| c.is_whitespace())
        .next()
        .unwrap_or("");
    name.rsplit(':').next().unwrap_or(name).to_string()
}

/// Join `target` onto the rels `base` directory and normalize `.`/`..`.
fn normalize_join(base: &str, target: &str) -> String {
    let combined = format!("{base}{target}");
    let mut parts: Vec<&str> = Vec::new();
    for seg in combined.split('/') {
        match seg {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            s => parts.push(s),
        }
    }
    parts.join("/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wellformed_detects_mismatch() {
        assert!(wellformed("<a><b/></a>").is_none());
        assert!(wellformed("<a><b></a>").is_some()); // unclosed b
        assert!(wellformed("<a></b>").is_some()); // mismatched
        assert!(wellformed("<?xml?><a><!-- c --><b/></a>").is_none());
    }

    #[test]
    fn direct_children_skips_nested_same_named() {
        // pPr contains a nested rPr; its children must not leak into pPr's list
        let xml = "<w:pPr><w:pStyle/><w:rPr><w:b/></w:rPr><w:jc/></w:pPr>";
        let blocks = direct_children_of(xml, "w:pPr");
        assert_eq!(blocks, vec![vec!["pStyle", "rPr", "jc"]]);
    }

    #[test]
    fn child_order_flags_out_of_sequence() {
        let mut v = Vec::new();
        // jc (pos 6) before numPr (pos 3) -> violation
        check_child_order("<w:pPr><w:jc/><w:numPr/></w:pPr>", &mut v);
        assert_eq!(v.len(), 1);
        let mut ok = Vec::new();
        check_child_order("<w:pPr><w:numPr/><w:jc/></w:pPr>", &mut ok);
        assert!(ok.is_empty());
    }

    #[test]
    fn field_and_bookmark_pairing() {
        let mut v = Vec::new();
        check_fields_and_bookmarks(
            "<w:fldChar w:fldCharType=\"begin\"/><w:bookmarkStart w:id=\"1\"/>",
            &mut v,
        );
        // missing fldChar end + missing bookmarkEnd
        assert!(v.iter().any(|s| s.contains("unbalanced complex fields")));
        assert!(v.iter().any(|s| s.contains("no matching bookmarkEnd")));
    }

    #[test]
    fn normalize_join_resolves_dotdot() {
        assert_eq!(
            normalize_join("word/", "media/image1.png"),
            "word/media/image1.png"
        );
        assert_eq!(
            normalize_join("word/", "../customXml/item.xml"),
            "customXml/item.xml"
        );
        assert_eq!(normalize_join("", "word/document.xml"), "word/document.xml");
    }
}
