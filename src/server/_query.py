from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from sqlalchemy import text

from ._common import db
from ._db import metadata
from ._printer import create_printer
from ._validate import DateRange, extract_strings


def date_string(value: int) -> str:
    # converts a date integer (YYYYMMDD) into a date string (YYYY-MM-DD)
    # $value: the date as an 8-digit integer
    year = int(value / 10000) % 10000
    month = int(value / 100) % 100
    day = value % 100
    return "{0:04d}-{1:02d}-{2:02d}".format(year, month, day)


def to_condition(
    field: str,
    value: Union[Tuple[str, str], str, Tuple[int, int], int],
    param_key: str,
    params: Dict[str, Any],
    formatter=lambda x: x,
):
    if isinstance(value, (list, tuple)):
        params[param_key] = formatter(value[0])
        params[f"{param_key}_2"] = formatter(value[1])
        return f"{field} BETWEEN :{param_key} AND :{param_key}_2"

    params[param_key] = formatter(value)
    return f"{field} = :{param_key}"


def filter_values(
    field: str,
    values: Sequence[Union[Tuple[str, str], str, Tuple[int, int], int]],
    param_key: str,
    params: Dict[str, Any],
    formatter=lambda x: x,
):
    # builds a SQL expression to filter strings (ex: locations)
    #   $field: name of the field to filter
    #   $values: array of values
    conditions = [
        to_condition(field, v, f"{param_key}_{i}", params, formatter)
        for i, v in enumerate(values)
    ]
    return f"({' OR '.join(conditions)})"


def filter_strings(
    field: str,
    values: Sequence[Union[Tuple[str, str], str]],
    param_key: str,
    params: Dict[str, Any],
):
    return filter_values(field, values, param_key, params)


def filter_integers(
    field: str,
    values: Sequence[Union[Tuple[int, int], int]],
    param_key: str,
    params: Dict[str, Any],
):
    return filter_values(field, values, param_key, params)


def filter_dates(
    field: str,
    values: Sequence[Union[Tuple[int, int], int]],
    param_key: str,
    params: Dict[str, Any],
):
    return filter_values(field, values, param_key, params, date_string)


def filter_fields(generator: Iterable[Dict[str, Any]]):
    fields = extract_strings("fields")
    if not fields:
        yield from generator
    else:
        for row in generator:
            filtered = dict()
            for field in fields:
                if field in row:
                    filtered[field] = row[field]
            yield filtered


def parse_row(
    row,
    fields_string: Optional[Sequence[str]] = None,
    fields_int: Optional[Sequence[str]] = None,
    fields_float: Optional[Sequence[str]] = None,
):
    parsed = dict()
    if fields_string:
        for f in fields_string:
            parsed[f] = row.get(f)
    if fields_int:
        for f in fields_int:
            parsed[f] = int(row.get(f)) if f in row else None
    if fields_float:
        for f in fields_float:
            parsed[f] = float(row.get(f)) if f in row else None
    return parsed


def parse_result(
    query: str,
    params: Dict[str, Any],
    fields_string: Optional[Sequence[str]] = None,
    fields_int: Optional[Sequence[str]] = None,
    fields_float: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """
    execute the given query and return the result as a list of dictionaries
    """
    return [
        parse_row(row, fields_string, fields_int, fields_float)
        for row in db.execute(text(query), **params)
    ]


def execute_queries(
    queries: Sequence[Tuple[str, Dict[str, Any]]],
    fields_string: Sequence[str],
    fields_int: Sequence[str],
    fields_float: Sequence[str],
):
    """
    execute the given queries and return the response to send them
    """
    p = create_printer()

    fields_to_send = set(extract_strings("fields") or [])
    if fields_to_send:
        fields_string = [v for v in fields_string if v in fields_to_send]
        fields_int = [v for v in fields_int if v in fields_to_send]
        fields_float = [v for v in fields_float if v in fields_to_send]

    def gen():
        for query, params in queries:
            if p.remaining_rows <= 0:
                # no more rows
                break
            # limit rows + 1 for detecting whether we would have more
            full_query = text(f"{query} LIMIT {p.remaining_rows + 1}")
            print(f'full_query: "{full_query}", params: {str(params)}', flush=True)
            r = db.execution_options(stream_results=True).execute(full_query, **params)
            for row in r:
                yield parse_row(row, fields_string, fields_int, fields_float)

    return p(gen())


def execute_query(
    query: str,
    params: Dict[str, Any],
    fields_string: Sequence[str],
    fields_int: Sequence[str],
    fields_float: Sequence[str],
):
    """
    execute the given query and return the response to send it
    """
    return execute_queries([(query, params)], fields_string, fields_int, fields_float)
