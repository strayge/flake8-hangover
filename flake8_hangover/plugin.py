import ast
import tokenize
from typing import (
    Any,
    Dict,
    Generator,
    List,
    Optional,
    Tuple,
    Type,
    Union,
)

from flake8.processor import count_parentheses

TAB_SIZE = 4


class Messages:
    """Linter messages."""

    FHG001 = 'FHG001 Function argument has hanging indentation'
    FHG002 = 'FHG002 Function call positional argument has hanging indentation'
    FHG003 = 'FHG003 Function call keyword argument has hanging indentation'
    FHG004 = 'FHG004 First function argument must be on new line'
    FHG005 = 'FHG005 Function close bracket must be on new line'
    FHG006 = 'FHG006 Function close bracket got over indentation'
    FHG007 = 'FHG007 Assignment close bracket got over indentation'


class Visitor(ast.NodeVisitor):
    """Class for visiting ast nodes."""

    def __init__(self, tokens: List[tokenize.TokenInfo]) -> None:
        """Initialize class instance."""
        self.errors: Dict[Tuple[int, int], str] = {}
        self._tokens = tokens

    def add_error(self, lineno: int, offset: int, error: str) -> None:
        key = (lineno, offset)
        if key not in self.errors:
            self.errors[key] = error

    def visit_Call(self, node: ast.Call) -> None:
        """Visit ``Call`` node."""
        cur_lineno = node.lineno
        func_name_offset = None
        node_end_lineno = node.end_lineno or 0
        node_end_col_offset = node.end_col_offset or 0
        last_inner_lineno = cur_lineno  # not include args which started at the same line as node

        # Iterate over positional arguments
        for arg in node.args:
            arg_col_offset = self._get_arg_col_offset(arg)
            arg_lineno = self._get_arg_lineno(arg)

            if arg_lineno - cur_lineno == 1:
                if func_name_offset is None:
                    func_name_offset = self._get_func_name_offset(node)

                if arg_col_offset > func_name_offset or arg_col_offset % TAB_SIZE != 0:
                    self.add_error(arg_lineno, arg_col_offset, Messages.FHG002)

            cur_lineno = self._get_arg_end_lineno(arg, default=arg_lineno)
            if arg_lineno != node.lineno:
                last_inner_lineno = max(last_inner_lineno, cur_lineno)

        # Iterate over keyword arguments
        for kwarg in node.keywords:
            kwarg_col_offset = self._get_arg_col_offset(kwarg)
            kwarg_lineno = self._get_arg_lineno(kwarg)

            if kwarg_lineno - cur_lineno == 1:
                if func_name_offset is None:
                    func_name_offset = self._get_func_name_offset(node)

                if (
                    kwarg_col_offset > func_name_offset
                    or (kwarg.arg and kwarg_col_offset % TAB_SIZE != 0)
                ):
                    self.add_error(kwarg_lineno, kwarg_col_offset, Messages.FHG003)

            cur_lineno = self._get_arg_end_lineno(kwarg, default=kwarg_lineno)
            if getattr(kwarg, 'lineno', kwarg_lineno) != node.lineno:
                last_inner_lineno = max(last_inner_lineno, cur_lineno)

        node_meaning_lineno = self._get_node_meaning_lineno(node)
        if node_meaning_lineno != cur_lineno:  # skip one-liners
            if node_end_lineno == last_inner_lineno:
                # close bracker shouldn't be on the same line as last param
                self.add_error(node_end_lineno, node_end_col_offset, Messages.FHG005)
            else:
                # check correct brackets number for last line
                self._check_close_brackets_position(node)

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit ``FunctionDef`` node."""
        self._check_func_args_indentations(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit ``AsyncFunctionDef`` node."""
        self._check_func_args_indentations(node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit ``Assign`` node."""
        self._check_close_brackets_position(node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Visit ``AnnAssign`` node."""
        self._check_close_brackets_position(node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Visit ``AugAssign`` node."""
        self._check_close_brackets_position(node)
        self.generic_visit(node)

    def _check_close_brackets_position(
        self,
        node: Union[ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Call],
    ) -> None:
        """Check all opened brackets from 1st line closes on last line (and no other code there)."""
        start_lineno = node.lineno
        end_lineno = node.end_lineno or start_lineno
        start_offset = node.col_offset
        end_offset = node.end_col_offset or start_offset
        if start_lineno == end_lineno:  # skip one-liners
            return
        start_line_tokens = self._get_tokens_for_line(start_lineno, None)
        start_indent = self._get_indent(start_line_tokens)
        open_brackets = sum((
            count_parentheses(0, token.string)
            for token in start_line_tokens
            if token.string and token.start[1] >= start_offset
        ))

        if self._check_ends_with_call(node, end_offset):
            return

        # all opened brackets on line with assign started should be closed on last assign` line
        if (
            open_brackets
            and end_offset != start_indent + open_brackets
        ):
            if isinstance(node, ast.Call):
                error = Messages.FHG006
            else:
                error = Messages.FHG007
            self.add_error(end_lineno, end_offset, error)

    def _check_ends_with_call(self, node: Any, end_offset: int) -> bool:
        inner_end = None
        if isinstance(node, ast.Call):
            inner_end = node.func.end_col_offset
        elif isinstance(node.value, ast.Call):
            inner_end = node.value.end_col_offset

        return inner_end is not None and inner_end <= end_offset

    def _check_func_args_indentations(self, node: Any) -> None:
        """Check indentations in function args/kwargs."""
        cur_lineno = node.lineno
        first_argument = None
        multiline_arguments = False

        for i, arg in enumerate(node.args.args):
            if i == 0:
                first_argument = (arg.lineno, arg.col_offset)

            if arg.lineno != cur_lineno:
                if arg.col_offset != node.col_offset + 4:
                    self.add_error(arg.lineno, arg.col_offset, Messages.FHG001)
                cur_lineno = arg.lineno
                multiline_arguments = True

        if (
            multiline_arguments
            and first_argument
            and first_argument[0] == node.lineno
        ):
            self.add_error(*first_argument, Messages.FHG004)

    def _get_arg_col_offset(self, obj: Any) -> int:
        """Get `col_offset` for object."""
        if isinstance(obj, ast.keyword):
            return obj.value.col_offset - len(str(obj.arg or '')) - 1  # 1 is for "="
        if isinstance(obj, ast.GeneratorExp):
            return self._get_arg_col_offset(obj.elt)
        return int(obj.col_offset)

    def _get_arg_lineno(self, obj: Any) -> int:
        if isinstance(obj, ast.keyword):
            return self._get_arg_lineno(obj.value)
        if isinstance(obj, ast.GeneratorExp):
            return self._get_arg_lineno(obj.elt)

        return int(obj.lineno)

    def _get_arg_end_lineno(self, obj: Any, default: Optional[int] = None) -> int:
        """Get `end_lineno` for object."""
        if isinstance(obj, ast.GeneratorExp):
            last_gen = obj.generators[-1]
            return max(
                self._get_arg_end_lineno(last_gen.target),
                self._get_arg_end_lineno(last_gen.iter),
            )

        return getattr(obj, 'end_lineno', int(obj.lineno if default is None else default))

    def _get_func_name_offset(self, node: Any) -> int:
        """Get function name offset."""
        func_name = self._get_func_name(node.func)
        return int(node.col_offset + max(len(func_name), TAB_SIZE))

    def _get_func_name(self, obj: Any) -> str:
        """Extract function full name from node.

        May not fully correctly work. For this cases function returns empty string.
        """
        try:
            if isinstance(obj, ast.Attribute):
                return f'{self._get_func_name(obj.value)}.{obj.attr}'
            if isinstance(obj, ast.Call):
                return self._get_func_name(obj.func)
            if isinstance(obj, ast.Subscript):
                return f'{self._get_func_name(obj.value)}[{self._get_func_name(obj.slice)}]'
            if isinstance(obj, ast.Index):
                return self._get_func_name(obj.value)
            if isinstance(obj, ast.Constant):
                return str(obj.value)

            return str(obj.id)
        except Exception:
            return ''

    def _get_node_meaning_lineno(self, node: ast.Call) -> int:
        return node.func.end_lineno or node.func.lineno

    def _get_tokens_for_line(
        self, line: int, col_offset: Optional[int] = None,
    ) -> List[tokenize.TokenInfo]:
        result = []
        for token in self._tokens:
            if (
                token.start[0] == line
                and (col_offset is None or token.start[1] >= col_offset)
            ):
                result.append(token)
        return result

    def _get_indent(self, tokens: List[tokenize.TokenInfo]) -> int:
        for token in tokens:
            if token.type == tokenize.INDENT:
                return token.end[1]
        if tokens:
            return tokens[0].start[1]
        return 0


class Plugin:
    """Class to run flake8 plugin."""

    name = 'flake8-hangover'

    def __init__(self, tree: ast.AST, file_tokens: List[tokenize.TokenInfo]):
        """Initialize class instance."""
        self._tree = tree
        self._tokens = file_tokens

    @property
    def version(self) -> str:
        """Get package version."""
        from . import __version__
        return __version__

    def run(self) -> Generator[Tuple[int, int, str, Type[Any]], None, None]:
        """Run plugin."""
        visitor = Visitor(tokens=self._tokens)
        visitor.visit(self._tree)

        for error_key, error_msg in visitor.errors.items():
            lineno, col_offset = error_key
            yield lineno, col_offset, error_msg, type(self)
