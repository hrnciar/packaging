from ast import literal_eval
from typing import Any, List, NamedTuple, Tuple, Union

from ._tokenizer import Tokenizer


class Node:
    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}('{self}')>"

    def serialize(self) -> str:
        raise NotImplementedError


class Variable(Node):
    def serialize(self) -> str:
        return str(self)


class Value(Node):
    def serialize(self) -> str:
        return f'"{self}"'


class Op(Node):
    def serialize(self) -> str:
        return str(self)


MarkerVar = Union[Variable, Value]
MarkerItem = Tuple[MarkerVar, Op, MarkerVar]
# MarkerAtom = Union[MarkerItem, List["MarkerAtom"]]
# MarkerList = List[Union["MarkerList", MarkerAtom, str]]
# mypy does not suport recursive type definition
# https://github.com/python/mypy/issues/731
MarkerAtom = Any
MarkerList = List[Any]


class Requirement(NamedTuple):
    name: str
    url: str
    extras: List[str]
    specifier: str
    marker: str


def parse_named_requirement(requirement: str) -> Requirement:
    """
    named_requirement: IDENTIFIER extras* (URL_SPEC | specifier)* (SEMICOLON marker_expr)*
    """
    tokens = Tokenizer(requirement)
    tokens.expect("IDENTIFIER", error_message="Expression must begin with package name")
    name = tokens.read("IDENTIFIER").text
    extras = parse_extras(tokens)
    specifier = ""
    url = ""
    if tokens.match("URL_SPEC"):
        url = tokens.read().text[1:].strip()
    elif not tokens.match("stringEnd"):
        specifier = parse_specifier(tokens)
    if tokens.try_read("SEMICOLON"):
        marker = ""
        while not tokens.match("stringEnd"):
            # we don't validate markers here, it's done later as part of
            # packaging/requirements.py
            marker += tokens.read().text
    else:
        marker = ""
        tokens.expect(
            "stringEnd",
            error_message="Expected semicolon (followed by markers) or end of string",
        )
    return Requirement(name, url, extras, specifier, marker)


def parse_extras(tokens: Tokenizer) -> List[str]:
    """
    extras: (LBRACKET IDENTIFIER (COMMA IDENTIFIER)* RBRACKET)*
    """
    extras = []
    if tokens.try_read("LBRACKET"):
        while tokens.match("IDENTIFIER"):
            extras.append(tokens.read("IDENTIFIER").text)
            if not tokens.match("RBRACKET"):
                tokens.expect("COMMA", error_message="Missing comma after extra")
                tokens.read("COMMA")
            if not tokens.match("COMMA") and tokens.match("RBRACKET"):
                break
        tokens.expect("RBRACKET", error_message="Closing square bracket is missing")
        tokens.read("RBRACKET")
    return extras


def parse_specifier(tokens: Tokenizer) -> str:
    """
    specifier: LPAREN (OP VERSION (COMMA OP VERSION)*)* RPAREN | (OP VERSION (COMMA OP VERSION)*)*
    """
    parsed_specifiers = ""
    lparen = False
    if tokens.try_read("LPAREN"):
        lparen = True
    while tokens.match("OP"):
        parsed_specifiers += tokens.read("OP").text
        if tokens.match("VERSION"):
            parsed_specifiers += tokens.read("VERSION").text
        else:
            tokens.raise_syntax_error(message="Missing version")
        if not tokens.match("COMMA"):
            break
        tokens.expect("COMMA", error_message="Missing comma after version")
        parsed_specifiers += tokens.read("COMMA").text
    if lparen and not tokens.try_read("RPAREN"):
        tokens.raise_syntax_error(message="Closing right parenthesis is missing")
    return parsed_specifiers


def parse_marker_expr(tokens: Tokenizer) -> MarkerList:
    """
    marker_expr: marker_atom (BOOLOP marker_atom)+
    """
    expression = [parse_marker_atom(tokens)]
    while tokens.match("BOOLOP"):
        tok = tokens.read("BOOLOP")
        expr_right = parse_marker_atom(tokens)
        expression.extend((tok.text, expr_right))
    return expression


def parse_marker_atom(tokens: Tokenizer) -> MarkerAtom:
    """
    marker_atom: LPAREN marker_expr RPAREN | marker_item
    """
    if tokens.try_read("LPAREN"):
        marker = parse_marker_expr(tokens)
        if not tokens.try_read("RPAREN"):
            tokens.raise_syntax_error(message="Closing right parenthesis is missing")
        return marker
    else:
        return parse_marker_item(tokens)


def parse_marker_item(tokens: Tokenizer) -> MarkerItem:
    """
    marker_item: marker_var marker_op marker_var
    """
    marker_var_left = parse_marker_var(tokens)
    marker_op = parse_marker_op(tokens)
    marker_var_right = parse_marker_var(tokens)
    return (marker_var_left, marker_op, marker_var_right)


def parse_marker_var(tokens: Tokenizer) -> MarkerVar:
    """
    marker_var: variable | python_str
    """
    if tokens.match("VARIABLE"):
        return parse_variable(tokens)
    else:
        return parse_python_str(tokens)


def parse_variable(tokens: Tokenizer) -> Variable:
    #TODO: better name for rule?
    """
    variable: VARIABLE
    """
    env_var = tokens.read("VARIABLE").text.replace(".", "_")
    if (
        env_var == "platform_python_implementation"
        or env_var == "python_implementation"
    ):
        return Variable("platform_python_implementation")
    else:
        return Variable(env_var)


def parse_python_str(tokens: Tokenizer) -> Value:
    """
    python_str: QUOTED_STRING
    """
    if tokens.match("QUOTED_STRING"):
        python_str = literal_eval(tokens.read().text)
        return Value(str(python_str))
    else:
        return tokens.raise_syntax_error(
            message="String with single or double quote at the beginning is expected"
        )


def parse_marker_op(tokens: Tokenizer) -> Op:
    """
    marker_op: IN | NOT IN | OP
    """
    if tokens.try_read("IN"):
        return Op("in")
    elif tokens.try_read("NOT"):
        tokens.expect("IN", error_message="NOT token must be follewed by IN token")
        tokens.read("IN")
        return Op("not in")
    elif tokens.match("OP"):
        return Op(tokens.read().text)
    else:
        return tokens.raise_syntax_error(
            message='Couldn\'t parse marker operator. Expecting one of \
            "<=, <, !=, ==, >=, >, ~=, ===, not, not in"'
        )
