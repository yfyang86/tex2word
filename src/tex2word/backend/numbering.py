"""Generation of ``word/numbering.xml``.

For V1 Sprint 1 we ship a minimal-but-valid numbering part defining a bullet
list (abstractNumId 0) and a decimal list (abstractNumId 1), with concrete
``num`` instances 1 (bullet) and 2 (decimal). Sprint 3 extends this for nested
``itemize``/``enumerate``.
"""

from __future__ import annotations

_NUMBERING_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="0">
    <w:multiLevelType w:val="hybridMultilevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="&#8226;"/>
      <w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr>
      <w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol" w:hint="default"/></w:rPr>
    </w:lvl>
    <w:lvl w:ilvl="1">
      <w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="&#9702;"/>
      <w:lvlJc w:val="left"/><w:pPr><w:ind w:left="1440" w:hanging="360"/></w:pPr>
      <w:rPr><w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:hint="default"/></w:rPr>
    </w:lvl>
    <w:lvl w:ilvl="2">
      <w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="&#9642;"/>
      <w:lvlJc w:val="left"/><w:pPr><w:ind w:left="2160" w:hanging="360"/></w:pPr>
      <w:rPr><w:rFonts w:ascii="Wingdings" w:hAnsi="Wingdings" w:hint="default"/></w:rPr>
    </w:lvl>
    <w:lvl w:ilvl="3">
      <w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="&#8226;"/>
      <w:lvlJc w:val="left"/><w:pPr><w:ind w:left="2880" w:hanging="360"/></w:pPr>
      <w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol" w:hint="default"/></w:rPr>
    </w:lvl>
    <w:lvl w:ilvl="4">
      <w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="&#9702;"/>
      <w:lvlJc w:val="left"/><w:pPr><w:ind w:left="3600" w:hanging="360"/></w:pPr>
      <w:rPr><w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:hint="default"/></w:rPr>
    </w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="1">
    <w:multiLevelType w:val="hybridMultilevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/>
      <w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="1">
      <w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="(%2)"/>
      <w:lvlJc w:val="left"/><w:pPr><w:ind w:left="1440" w:hanging="360"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="2">
      <w:start w:val="1"/><w:numFmt w:val="lowerRoman"/><w:lvlText w:val="%3."/>
      <w:lvlJc w:val="right"/><w:pPr><w:ind w:left="2160" w:hanging="180"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="3">
      <w:start w:val="1"/><w:numFmt w:val="upperLetter"/><w:lvlText w:val="%4."/>
      <w:lvlJc w:val="left"/><w:pPr><w:ind w:left="2880" w:hanging="360"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="4">
      <w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%5."/>
      <w:lvlJc w:val="left"/><w:pPr><w:ind w:left="3600" w:hanging="360"/></w:pPr>
    </w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="2">
    <w:multiLevelType w:val="multilevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1"/>
      <w:lvlJc w:val="left"/><w:pStyle w:val="Heading1"/>
      <w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="1">
      <w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2"/>
      <w:lvlJc w:val="left"/><w:pStyle w:val="Heading2"/>
      <w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="2">
      <w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2.%3"/>
      <w:lvlJc w:val="left"/><w:pStyle w:val="Heading3"/>
      <w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="3">
      <w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2.%3.%4"/>
      <w:lvlJc w:val="left"/><w:pStyle w:val="Heading4"/>
      <w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr>
    </w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="3">
    <w:multiLevelType w:val="multilevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/><w:numFmt w:val="upperLetter"/><w:lvlText w:val="%1"/>
      <w:lvlJc w:val="left"/><w:pStyle w:val="Heading1"/>
      <w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="1">
      <w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2"/>
      <w:lvlJc w:val="left"/><w:pStyle w:val="Heading2"/>
      <w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="2">
      <w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2.%3"/>
      <w:lvlJc w:val="left"/><w:pStyle w:val="Heading3"/>
      <w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr>
    </w:lvl>
    <w:lvl w:ilvl="3">
      <w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2.%3.%4"/>
      <w:lvlJc w:val="left"/><w:pStyle w:val="Heading4"/>
      <w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr>
    </w:lvl>
  </w:abstractNum>
  <w:abstractNum w:abstractNumId="4">
    <w:multiLevelType w:val="singleLevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/><w:numFmt w:val="upperRoman"/><w:lvlText w:val="Part %1"/>
      <w:lvlJc w:val="left"/><w:suff w:val="space"/>
      <w:pPr><w:ind w:left="0" w:hanging="0"/></w:pPr>
    </w:lvl>
  </w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
  <w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>
  <w:num w:numId="3"><w:abstractNumId w:val="2"/></w:num>
  <w:num w:numId="4"><w:abstractNumId w:val="3"/></w:num>
  <w:num w:numId="5"><w:abstractNumId w:val="4"/></w:num>
</w:numbering>
"""

#: numId for bullet (itemize) and decimal (enumerate) lists.
BULLET_NUM_ID = 1
DECIMAL_NUM_ID = 2
#: numId for the multilevel heading (section) numbering scheme.
HEADING_NUM_ID = 3
#: numId for appendix headings (top level lettered A, B, ...; then A.1, A.1.1).
HEADING_APPENDIX_NUM_ID = 4
#: numId for \part headings ("Part I", upper-roman, counter independent of sections).
PART_NUM_ID = 5


def numbering_xml() -> bytes:
    return _NUMBERING_XML.encode("utf-8")
