"""Small record/token-preserving helpers for the JP/KR optional-column transition.

Never round-trip untouched CSV records, numeric tokens or quoted provenance.
"""
import csv
import io

def csv_records(text: str) -> list[tuple[list[str], str]]:
    """Parse logical CSV records while retaining their exact original text.

    Physical-line splitting is unsafe for quoted multiline notes (and
    str.splitlines also splits valid field characters such as U+0085).
    """
    stream = io.StringIO(text, newline="")
    records = []
    start = 0
    for fields in csv.reader(stream, strict=True):
        end = stream.tell()
        records.append((fields, text[start:end]))
        start = end
    return records


def record_ending(record: str) -> str:
    for ending in ("\r\n", "\n", "\r"):
        if record.endswith(ending):
            return ending
    return ""



def append_column(columns, header, records, name):
    """Append one empty field, retaining every old token and record ending."""
    def add(raw, value):
        eol = record_ending(raw)
        body = raw[:-len(eol)] if eol else raw
        return body + ',' + value + eol
    return columns + [name], add(header, name), [
        (fields + [''], add(raw, '')) if fields else (fields, raw)
        for fields, raw in records]


def legacy_fcev(row, previous=None, historical=False):
    """Unknown historical detail stays inclusive Other, including on --force.

    A previously recorded known split may be revised by its normal source
    policy. A blank old split never becomes measured data automatically.
    """
    row = dict(row)
    previous_known = previous is not None and str(previous.get('FCEV') if previous.get('FCEV') is not None else '').strip() != ''
    if 'FCEV' in row and previous_known and row['FCEV'] in (None, ''):
        # An unavailable fallback cannot erase an already confirmed split.
        # If the inclusive remainder changed, refuse an unknowable revision.
        inclusive = float(previous.get('OTHERS') or 0) + float(previous['FCEV'])
        if abs(float(row.get('OTHERS') or 0) - inclusive) > 1e-6:
            raise ValueError('Cannot revise known FCEV without a confirmed source split')
        row['FCEV'] = float(previous['FCEV'])
        row['OTHERS'] = float(previous.get('OTHERS') or 0)
    elif 'FCEV' in row and ((previous is not None and not previous_known)
                            or (previous is None and historical)):
        row['OTHERS'] = float(row.get('OTHERS') or 0) + float(row.get('FCEV') or 0)
        row['FCEV'] = None
    return row


def keep_numeric_tokens(values, previous, columns):
    """A numerically equal refreshed field keeps its original spelling."""
    for c in columns:
        if c not in previous or values.get(c) in (None, '') or previous[c] == '':
            continue
        try:
            if float(values[c]) == float(previous[c]): values[c] = previous[c]
        except (ValueError, TypeError):
            pass
