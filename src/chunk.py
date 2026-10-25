"""Chunk reviewed Markdown. Python 3.10+, standard library only."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PAGE = re.compile(r'<!--\s*source_page:\s*(\d+)\s*-->', re.I)
HEADING = re.compile(r'^(#{1,6})\s+(.+)$')
SEPARATOR = re.compile(r'^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$')


def estimate(text):
    """Heuristic only, not a model tokenizer."""
    return max(1, (len(text) + 3) // 4)


def sections(markdown):
    """Explicit headings define context; page markers update provenance."""
    heading, lines, page, start = 'Document', [], None, 1
    for number, raw in enumerate(markdown.splitlines(), 1):
        marker = PAGE.fullmatch(raw.strip())
        if marker:
            page = int(marker.group(1))
            continue
        match = HEADING.match(raw)
        if match:
            if lines:
                yield heading, lines, start
            heading, lines, start = match.group(2).strip(), [], number
        else:
            lines.append((raw, page, number))
    if lines:
        yield heading, lines, start


def cells(row):
    return [x.strip() for x in re.split(r'(?<!\\)\|', row.strip().strip('|'))]


def blocks(lines):
    result, paragraph, i = [], [], 0

    def flush():
        if paragraph:
            result.append(('text', paragraph.copy()))
            paragraph.clear()

    while i < len(lines):
        raw = lines[i][0]
        if i + 1 < len(lines) and '|' in raw and SEPARATOR.fullmatch(lines[i + 1][0]):
            flush()
            table = [lines[i], lines[i + 1]]
            i += 2
            while i < len(lines) and '|' in lines[i][0] and lines[i][0].strip():
                table.append(lines[i])
                i += 1
            result.append(('table', table))
            continue
        if raw.strip():
            paragraph.append(lines[i])
        else:
            flush()
        i += 1
    flush()
    return result


def parameter_groups(rows, electrical=False):
    """Keep continuation rows with their parameter, preserving source order.

    TI exports can have an unnamed symbol column before PARAMETER. They can
    also place the first dropout condition above the vertically merged VDO
    label; recognize that condition rather than assigning it to load regulation.
    """
    header = [x.casefold() for x in cells(rows[0][0])]
    names = {'parameter', 'symbol', 'parameter / symbol', 'parameter/symbol'}
    candidates = [i for i, value in enumerate(header) if value in names]
    if not candidates:
        return None
    column = candidates[0]
    if electrical and column == 1 and not header[0]:
        column = 0
    groups, group, key = [], [], None
    for row in rows[2:]:
        values = cells(row[0])
        value = values[column].casefold() if column < len(values) else ''
        compact = re.sub(r'[\s_{}()]', '', row[0]).casefold()
        if electrical and not value and re.search(r'vin=0\.98[×*]vout', compact):
            value = 'vdo'
        # EN-high and EN-low jointly define the enable input voltage ranges.
        # Group the rows without changing their original labels or values.
        if electrical:
            normalized = re.sub(r'[\s_{}()]', '', value)
            if normalized in {'venhigh', 'venlow'}:
                value = 'ven-levels'
        if value and group and value != key:
            groups.append(group)
            group = []
        if value:
            key = value
        group.append(row)
    if group:
        groups.append(group)
    return groups


def split_table(rows, budget, overhead, warnings, electrical=False):
    headers = rows[:2]
    if not electrical and estimate('\n'.join(x[0] for x in rows)) + overhead <= budget:
        return [rows]
    groups = parameter_groups(rows, electrical)
    if groups is None:
        warnings.append('Table retained whole: no Parameter or Symbol header for safe grouping.')
        return [rows]
    # Electrical parameters are separate retrieval units even below the limit.
    if electrical:
        return [headers + group for group in groups] or [rows]
    parts, current = [], []
    for group in groups:
        proposed = headers + current + group
        if current and overhead + estimate('\n'.join(x[0] for x in proposed)) > budget:
            parts.append(headers + current)
            current = []
        current.extend(group)
    if current:
        parts.append(headers + current)
    return parts or [rows]


def document_title(markdown, family):
    """Recognize a leading title without treating the first numbered section as one."""
    for number, line in enumerate(markdown.splitlines(), 1):
        match = HEADING.match(line)
        if not match or '[www.ti.com]' in line:
            continue
        title = match.group(2).strip()
        if not re.match(r'\d+(?:\.|\s)', title) and (
            match.group(1) == '#' or family.casefold() in title.casefold()
        ):
            return title, number
        break
    return None, None


def parameter_name(selected):
    """Read names from the PARAMETER column; never guess from numeric cells."""
    names = []
    for kind, table in blocks(selected):
        if kind != 'table':
            continue
        header = [value.casefold() for value in cells(table[0][0])]
        if 'parameter' not in header:
            continue
        column = header.index('parameter')
        for row in table[2:]:
            values = cells(row[0])
            if column >= len(values):
                continue
            # Remove footnote markers from display names only; source rows stay intact.
            name = re.sub(r'\s*\(\d+\)', '', values[column]).strip()
            if name and name not in names:
                names.append(name)
    return ' / '.join(names) if names else None


def labelled_specifications(selected):
    """Add explicit labels using column headers; never infer missing values.

    This expects the reviewed Markdown electrical tables with complete names,
    units and conditions. Original tables/footnotes are preserved separately.
    """
    records = []
    for kind, table in blocks(selected):
        if kind != 'table':
            continue
        header = [value.strip().casefold() for value in cells(table[0][0])]
        required = {'parameter', 'min', 'typ', 'max', 'unit'}
        if not required.issubset(header):
            continue
        positions = {name: header.index(name) for name in required}
        def value(values, name):
            index = positions[name]
            return values[index].strip() if index < len(values) else ''
        for row in table[2:]:
            values = cells(row[0])
            if len(values) != len(header):
                raise ValueError('Electrical table row has mismatched columns; repair Markdown before chunking.')
            name = value(values, 'parameter')
            if not name:
                raise ValueError('Electrical table row is missing its parameter name; review merged-cell cleanup.')
            unit = value(values, 'unit')
            symbol = values[header.index('symbol')] if 'symbol' in header else ''
            condition = values[header.index('test conditions')] if 'test conditions' in header else ''
            lines = ['Parameter: ' + name]
            if symbol:
                lines.append('Symbol: ' + symbol)
            for field, label in [('min', 'Minimum'), ('typ', 'Typical'), ('max', 'Maximum')]:
                raw = value(values, field)
                # Do not invent a min/max, including when the typical cell is filled.
                displayed = raw if raw else 'not specified'
                if raw and unit:
                    displayed += ' ' + unit
                lines.append(label + ': ' + displayed)
            lines.append('Unit: ' + (unit or 'not separately specified; preserve symbols in values'))
            lines.append('Row-specific conditions: ' + (condition or 'none listed; use applicable table defaults'))
            if symbol.casefold() == 'ven(high)':
                lines.append('Enabled input range: ' + value(values, 'min') + ' V to ' + value(values, 'max') + ('' if value(values, 'max') == 'VIN' else ' V'))
            elif symbol.casefold() == 'ven(low)':
                lines.append('Disabled input range: ' + value(values, 'min') + ' V to ' + value(values, 'max') + ('' if value(values, 'max') == 'VIN' else ' V'))
            lines.append('Apply the original table defaults except where this row overrides them; use only relevant footnotes.')
            records.append('\n'.join(lines))
    if not records:
        return ''
    return ('Explicit specification labels transcribed from the table columns\n'
            'A typical value is not a guaranteed minimum or maximum.\n\n'
            + '\n\n'.join(records))


def build(markdown, source, family, document_id, target=450, maximum=600):
    if not 0 < target <= maximum:
        raise ValueError('Require 0 < target <= maximum')
    chunks, warnings = [], []
    title, title_line = document_title(markdown, family)

    def add(kind, heading, selected):
        content = '\n'.join(x[0] for x in selected).strip()
        if not content:
            return
        pages = sorted({x[1] for x in selected if x[1] is not None})
        parameter = None
        if kind == 'table' and re.search(r'electrical\s+characteristics', heading, re.I):
            parameter = parameter_name(selected)
        retrieval_heading = heading + (' | ' + parameter if parameter else '')
        if parameter:
            labelled = labelled_specifications(selected)
            if labelled:
                content = labelled + '\n\nOriginal table and context\n' + content
        text = family + ' | ' + retrieval_heading + '\n\n' + content
        digest = hashlib.sha256((kind + heading + repr(selected)).encode()).hexdigest()[:12]
        missing = any(x[1] is None for x in selected if x[0].strip())
        if missing:
            warnings.append(f'Missing page provenance in {heading}; add source_page markers.')
        if estimate(text) > maximum:
            warnings.append(f'Oversized {kind} chunk in {heading}; retained to preserve meaning.')
        chunks.append(dict(chunk_id=f'{document_id}-{digest}', document_id=document_id,
            document_title=title, part_family=family, section=heading, pages=pages,
            parameter_name=parameter, retrieval_heading=retrieval_heading,
            type=kind, text=text, source_markdown=str(source),
            source_lines=[min(x[2] for x in selected), max(x[2] for x in selected)],
            estimated_tokens=estimate(text), page_provenance_complete=not missing))

    for heading, lines, start in sections(markdown):
        # Front matter and the document identity are metadata, not retrieval units.
        if title_line is not None and start <= title_line:
            continue
        raw = '\n'.join(x[0] for x in lines)
        if re.search(r'exclude_from_index\s*:\s*true|review_status\s*:\s*pending', raw, re.I):
            warnings.append(f'Skipped pending section: {heading}')
            continue
        if re.match(r'figure\s+\d+\b', heading, re.I):
            warnings.append(f'Skipped figure section: {heading}')
            continue
        cleaned = []
        for line, page, number in lines:
            if re.match(r'^\s*!\[', line) or re.match(r'^\s*(?:Figure\s+\d+[.:]|\[www\.ti\.com\])', line, re.I):
                continue
            if '<!--' in line:
                continue
            cleaned.append((line, page, number))
        parsed = blocks(cleaned)
        tables = [(i, block) for i, (kind, block) in enumerate(parsed) if kind == 'table']
        if tables:
            # Conservatively repeat all same-section conditions/notes. Preserve
            # their relative position so introductions precede, footnotes follow.
            # Do not emit this prose again as standalone chunks.
            for index, table in tables:
                before = [line for kind, block in parsed[:index] if kind == 'text' for line in block]
                after = [line for kind, block in parsed[index + 1:] if kind == 'text' for line in block]
                overhead = estimate('\n'.join(x[0] for x in before + after) + heading + family)
                electrical = bool(re.search(r'electrical\s+characteristics', heading, re.I))
                for part in split_table(table, maximum, overhead, warnings, electrical):
                    add('table', heading, before + part + after)
            continue
        current = []
        for kind, paragraph in parsed:
            if current and estimate('\n'.join(x[0] for x in current + paragraph)) > maximum:
                add('text', heading, current)
                current = []
            current.extend(paragraph)
            if estimate('\n'.join(x[0] for x in current)) >= target:
                add('text', heading, current)
                current = []
        if current:
            add('text', heading, current)
    return chunks, warnings


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, default=Path('data/chunks/TLV700.jsonl'))
    p.add_argument('--family', default='TLV700')
    p.add_argument('--document-id', default='TLV700-reviewed')
    p.add_argument('--target-tokens', type=int, default=450)
    p.add_argument('--max-tokens', type=int, default=600)
    p.add_argument('--strict-pages', action='store_true')
    a = p.parse_args()
    if not 0 < a.target_tokens <= a.max_tokens:
        p.error('Require 0 < target-tokens <= max-tokens')
    chunks, warnings = build(a.input.read_text(encoding='utf-8-sig'), a.input, a.family,
                             a.document_id, a.target_tokens, a.max_tokens)
    if not chunks:
        p.error('No searchable content found')
    if a.strict_pages and any(not c['page_provenance_complete'] for c in chunks):
        p.error('Missing source pages; output was not written. Add markers before content.')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in chunks), encoding='utf-8')
    report = a.output.with_suffix('.review.json')
    report.write_text(json.dumps({'chunks': len(chunks), 'warnings': sorted(set(warnings))}, indent=2), encoding='utf-8')
    print(f'Wrote {len(chunks)} chunks to {a.output}; review warnings in {report}')
    for warning in sorted(set(warnings)):
        print('WARNING:', warning, file=sys.stderr)


if __name__ == '__main__':
    main()
