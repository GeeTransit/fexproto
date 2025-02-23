# Optional RPython imports
try:
    from rpython.rlib.rsre import rsre_re as re
    from rpython.rlib import jit
    from rpython.rlib import objectmodel
    from rpython.rlib import rfile
except ImportError:
    import re
    class jit(object):
        class JitDriver(object):
            def __init__(self, **kwargs): pass
            def jit_merge_point(self, **kwargs): pass
            def can_enter_jit(self, **kwargs): pass
        @staticmethod
        def set_param(*args): pass
        @staticmethod
        def set_user_param(*args): pass
        @staticmethod
        def promote(arg): return arg
        @staticmethod
        def promote_string(arg): return arg
        @staticmethod
        def elidable(func): return func
        @staticmethod
        def unroll_safe(func): return func
        @staticmethod
        def isvirtual(arg): return False
    class objectmodel(object):
        class specialize(object):
            @staticmethod
            def call_location(): return lambda func: func
    class rfile(object):
        if b"" == "":  # Python 2
            @staticmethod
            def create_stdio():
                import sys, os
                # TODO: is this the correct way to reopen files in binary mode?
                return (
                    os.fdopen(sys.stdin.fileno(), "rb", 0),
                    os.fdopen(sys.stdout.fileno(), "wb", 0),
                    os.fdopen(sys.stderr.fileno(), "wb", 0),
                )
        else:
            @staticmethod
            def create_stdio():
                import sys
                return sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer

# == Interpreter types and logic

class Object(object):
    _attrs_ = _immutable_fields_ = ()
class Nil(Object):
    _attrs_ = _immutable_fields_ = ()
class Ignore(Object):
    _attrs_ = _immutable_fields_ = ()
class Inert(Object):
    _attrs_ = _immutable_fields_ = ()
class Boolean(Object):
    _attrs_ = _immutable_fields_ = ("value",)
    def __init__(self, value):
        assert isinstance(value, bool)
        self.value = value
class Pair(Object):
    _attrs_ = _immutable_fields_ = ("car", "cdr")
    def __init__(self, car, cdr):
        assert isinstance(car, Object)
        assert isinstance(cdr, Object)
        self.car = car
        self.cdr = cdr
ImmutablePair = Pair
class MutablePair(Pair):
    _attrs_ = ("car", "cdr")
    _immutable_fields_ = ()
class Int(Object):
    _attrs_ = _immutable_fields_ = ("value",)
    def __init__(self, value):
        assert isinstance(value, int)
        self.value = value
class String(Object):
    _attrs_ = _immutable_fields_ = ("value",)
    def __init__(self, value):
        assert isinstance(value, bytes)
        self.value = value
class Symbol(Object):
    _attrs_ = _immutable_fields_ = ("name",)
    def __init__(self, name):
        assert isinstance(name, bytes)
        self.name = name
class Environment(Object):
    _immutable_fields_ = ("storage", "parent")
    def __init__(self, bindings, parent):
        assert parent is None or isinstance(parent, Environment)
        storage, localmap = _environment_tostoragemap(bindings)
        self.storage = storage
        self.parent = parent
        self.localmap = localmap
class Continuation(Object):
    _immutable_fields_ = ("env", "operative", "parent")
    _attrs_ = _immutable_fields_ + ("_should_enter", "_call_info")
    def __init__(self, env, operative, parent):
        assert env is None or isinstance(env, Environment)
        assert isinstance(operative, Operative)
        assert parent is None or isinstance(parent, Continuation)
        self.env = env
        self.operative = operative
        self.parent = parent
        self._should_enter = False
        self._call_info = None
class Combiner(Object):
    _attrs_ = _immutable_fields_ = ("num_wraps", "operative")
    def __init__(self, num_wraps, operative):
        self.num_wraps = num_wraps
        self.operative = operative
NIL = Nil()
IGNORE = Ignore()
INERT = Inert()
TRUE = Boolean(True)
FALSE = Boolean(False)

class Operative(object):
    _immutable_ = True
    def call(self, env, value, parent): assert False
class PrimitiveOperative(Operative):
    _immutable_ = True
    def __init__(self, func):
        self.func = func
    def call(self, env, value, parent):
        try:
            return self.func(env, value, parent)
        except RuntimeError as e:
            return f_error(parent, MutablePair(String(_c_str_to_bytes(e.message)), NIL))
class UserDefinedOperative(Operative):
    _immutable_ = True
    def __init__(self, env, envname, name, body):
        assert env is None or isinstance(env, Environment)
        self.env = env
        assert isinstance(envname, Symbol) or isinstance(envname, Ignore)
        self.envname = envname
        assert isinstance(name, Symbol) or isinstance(name, Ignore)
        self.name = name
        assert not isinstance(body, MutablePair)
        self.body = body
    def call(self, env, value, parent):
        call_env = Environment({}, self.env)
        envname = self.envname
        if isinstance(envname, Symbol):
            _environment_update(call_env, envname, env)
        name = self.name
        if isinstance(name, Symbol):
            _environment_update(call_env, name, value)
        return f_eval(call_env, self.body, parent)

def _f_noop(env, expr, parent):
    return f_return(parent, expr)
NOOP = PrimitiveOperative(_f_noop)

def _f_copy_immutable(expr):
    if not isinstance(expr, MutablePair):
        return expr
    # TODO: when mutation is introduced, support self-referencing structures
    car = _f_copy_immutable(expr.car)
    cdr = _f_copy_immutable(expr.cdr)
    return ImmutablePair(car, cdr)

# Exceptions

class ParsingError(Exception):
    def __init__(self, message, line_no, char_no):
        self.message = message
        # Note that line_no and char_no must be on the exception instance since
        # unlike internal errors, there is no "source expression" to locate.
        self.line_no = line_no
        self.char_no = char_no
OldRuntimeError = RuntimeError
class RuntimeError(OldRuntimeError):
    def __init__(self, message):
        # RPython exception instances don't have .message
        self.message = message
class EvaluationError(Exception):
    def __init__(self, value, parent=None):
        # Actual exception which stops the evaluation loop
        self.value = value
        self.parent = parent
class EvaluationDone(Exception):
    def __init__(self, value):
        # Resolved value which stops the evaluation loop
        self.value = value

def _f_error_cont(env, expr, parent):
    if isinstance(expr, Pair):
        original_parent = expr.car
        if isinstance(original_parent, Continuation):
            raise EvaluationError(expr.cdr, original_parent)
    raise EvaluationError(expr)
ERROR_CONT = Continuation(None, PrimitiveOperative(_f_error_cont), None)
def _f_evaluation_done(env, expr, parent):
    raise EvaluationDone(expr)
EVALUATION_DONE = PrimitiveOperative(_f_evaluation_done)

# Variable lookup and environment versioning

# We assume that most environments assign the same variables in the same order.
# This lets us optimize local variable lookups to be just an array access. See
# https://pypy.org/posts/2011/03/controlling-tracing-of-interpreter-with_21-6524148550848694588.html
class LocalMap(object):
    _attrs_ = _immutable_fields_ = ("transitions", "indexes")
    def __init__(self):
        self.transitions = {}  # bytes -> LocalMap
        self.indexes = {}  # bytes -> int
    @jit.elidable
    def find(self, name):
        return self.indexes.get(name, -1)
    @jit.elidable
    def new_localmap_with(self, name):
        assert isinstance(name, bytes)
        if name not in self.transitions:
            new = LocalMap()
            new.indexes.update(self.indexes)
            new.indexes[name] = len(self.indexes)
            self.transitions[name] = new
        return self.transitions[name]
_ROOT_LOCALMAP = LocalMap()

@jit.unroll_safe
def _environment_tostoragemap(bindings):
    storage = []
    localmap = _ROOT_LOCALMAP
    if bindings is not None and len(bindings) > 0:
        for key, value in bindings.items():  # TODO: should we sort?
            localmap = localmap.new_localmap_with(key)
            storage.append(value)
    return storage, localmap

@jit.unroll_safe
def _environment_lookup(env, name):
    # TODO: how to optimize constants? (usually global functions) Maybe look
    # into how PyPy stores metadata about variables' types, whether it gets
    # reassigned, and maybe even nested environments' types.
    name_name = name.name
    if not jit.isvirtual(name_name):
        jit.promote_string(name_name)
    while env is not None:
        # Promote the local map since the combiner calls should be the same,
        # hence variable lookups should be on the same lexical environments.
        jit.promote(env.localmap)
        index = env.localmap.find(name_name)
        if index >= 0:
            return env.storage[index]
        env = env.parent
    return None

def _environment_update(env, name, value):
    name_name = name.name
    if not jit.isvirtual(name_name):
        jit.promote_string(name_name)
    index = env.localmap.find(name_name)
    if index >= 0:
        env.storage[index] = value
    else:
        env.localmap = env.localmap.new_localmap_with(name_name)
        env.storage.append(value)

# Specialized environments

class StepWrappedEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("env", "args")
    def __init__(self, env, args):
        Environment.__init__(self, None, None)
        self.env = env
        self.args = args
class StepEvCarEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("env", "operative", "num_wraps", "todo", "p", "i", "res")
    def __init__(self, env, operative, num_wraps, todo, p, i, res):
        Environment.__init__(self, None, None)
        self.env = env
        self.operative = operative
        self.num_wraps = num_wraps
        self.todo = todo
        self.p = p
        self.i = i
        self.res = res
class FRemoteEvalEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("expression",)
    def __init__(self, expression):
        Environment.__init__(self, None, None)
        self.expression = expression
class FIfEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("env", "then", "orelse")
    def __init__(self, env, then, orelse):
        Environment.__init__(self, None, None)
        self.env = env
        self.then = then
        self.orelse = orelse
class FDefineEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("env", "name")
    def __init__(self, env, name):
        Environment.__init__(self, None, None)
        self.env = env
        self.name = name
class FBindsEnvironment(Environment):
    _immutable_fields_ = Environment._immutable_fields_ + ("name",)
    def __init__(self, name):
        Environment.__init__(self, None, None)
        self.name = name

# Core interpreter logic

def _f_toplevel_eval(env, expr):
    parent = Continuation(None, EVALUATION_DONE, None)
    parent._call_info = expr
    return f_eval(env, expr, parent)

def f_return(parent, obj):
    return None, obj, parent
def f_return_loop_constant(parent, obj):
    return obj, None, parent
def f_error(parent, value):
    # TODO: replace with abnormal pass when guarded continuations implemented
    return f_return(ERROR_CONT, MutablePair(parent, value))
def f_eval(env, obj, parent=None):
    # Don't let the JIT driver promote virtuals (such as mutable pairs
    # constructed at runtime)
    if jit.isvirtual(obj):
        next_continuation = Continuation(env, _STEP_EVAL, parent)
        return f_return(next_continuation, obj)
    return obj, env, parent

def _step_eval(env, obj, parent):
    return step_evaluate((obj, env, parent))
_STEP_EVAL = PrimitiveOperative(_step_eval)

def step_evaluate(state):
    obj, env, parent = state
    # Return values should usually not be promoted (red variables) unless they
    # are loop constants (green variables).
    if obj is None:  # normal return
        assert env is not None
        return parent.operative.call(parent.env, env, parent.parent)
    if env is None:  # loop constant
        assert obj is not None
        return parent.operative.call(parent.env, obj, parent.parent)
    if isinstance(obj, Symbol):
        assert isinstance(env, Environment)
        value = _environment_lookup(env, obj)
        if value is None:
            return f_error(parent, MutablePair(String(b"binding not found"), MutablePair(obj, NIL)))
        return f_return(parent, value)
    elif isinstance(obj, Pair):
        next_env = StepWrappedEnvironment(env, obj.cdr)
        next_continuation = Continuation(next_env, _STEP_CALL_WRAPPED, parent)
        next_continuation._call_info = obj.car
        return f_eval(env, obj.car, next_continuation)
    else:
        return f_return(parent, obj)

jitdriver = jit.JitDriver(
    greens=["expr"],
    reds=["env", "continuation"],
    is_recursive=True,
)

def fully_evaluate(state):
    expr, env, continuation = state
    try:
        while True:
            jitdriver.jit_merge_point(expr=expr, env=env, continuation=continuation)
            expr, env, continuation = step_evaluate((expr, env, continuation))
            if continuation._should_enter:
                jitdriver.can_enter_jit(expr=expr, env=env, continuation=continuation)
    except EvaluationDone as e:
        return e.value

# TODO: Look into how Pycket does runtime call-graph construction to
# automatically infer loops. See https://doi.org/10.1145/2858949.2784740
def _f_loop_constant(env, expr, parent):
    return f_return(parent, INERT)
def _f_loop_head(env, expr, parent):
    next_continuation = Continuation(None, _F_LOOP_CONSTANT, parent)
    next_continuation._should_enter = True
    return f_return_loop_constant(next_continuation, expr)
_F_LOOP_CONSTANT = PrimitiveOperative(_f_loop_constant)
_F_LOOP_HEAD = PrimitiveOperative(_f_loop_head)

@jit.unroll_safe
def _step_call_wrapped(static, combiner, parent):
    assert isinstance(static, StepWrappedEnvironment)
    env = static.env
    args = static.args
    if not isinstance(combiner, Combiner):
        raise RuntimeError("combiner call car must be combiner")
    # Promoting combiners should work in loops since otherwise the loop logic
    # would be different each iteration.
    if not jit.isvirtual(combiner):
        jit.promote(combiner)
    jit.promote(combiner.num_wraps)
    if not jit.isvirtual(combiner.operative):
        jit.promote(combiner.operative)
    if combiner.num_wraps == 0 or isinstance(args, Nil):
        return f_return(Continuation(env, combiner.operative, parent), args)
    c = args; p = 0
    while isinstance(c, Pair): p += 1; c = c.cdr
    if not isinstance(c, Nil):
        raise RuntimeError("applicative call args must be proper list")
    assert isinstance(args, Pair)
    next_expr = args.car
    next_env = StepEvCarEnvironment(env, combiner.operative, combiner.num_wraps, args.cdr, p, 0, NIL)
    next_continuation = Continuation(next_env, _STEP_CALL_EVCAR, parent)
    next_continuation._call_info = next_expr
    return f_eval(env, next_expr, next_continuation)
_STEP_CALL_WRAPPED = PrimitiveOperative(_step_call_wrapped)

@jit.unroll_safe
def _step_call_evcar(static, value, parent):
    assert isinstance(static, StepEvCarEnvironment)
    env = static.env
    assert isinstance(env, Environment)
    operative = static.operative
    assert isinstance(operative, Operative)
    num_wraps = static.num_wraps
    assert isinstance(num_wraps, int)
    todo = static.todo
    assert isinstance(todo, Nil) or isinstance(todo, Pair)
    p = static.p
    assert isinstance(p, int)
    i = static.i
    assert isinstance(i, int)
    res = static.res
    assert isinstance(res, Nil) or isinstance(res, Pair)
    res = MutablePair(value, res)
    i = i + 1
    if i == p:
        i = 0
        num_wraps = num_wraps - 1
        assert isinstance(todo, Nil)
        for _ in range(p): assert isinstance(res, Pair); todo = MutablePair(res.car, todo); res = res.cdr
        assert isinstance(todo, Pair)
        if num_wraps == 0:
            continuation = Continuation(env, operative, parent)
            return f_return(continuation, todo)
    assert isinstance(todo, Pair)
    next_env = StepEvCarEnvironment(env, operative, num_wraps, todo.cdr, p, i, res)
    next_expr = todo.car
    next_continuation = Continuation(next_env, _STEP_CALL_EVCAR, parent)
    next_continuation._call_info = next_expr
    return f_eval(env, next_expr, next_continuation)
_STEP_CALL_EVCAR = PrimitiveOperative(_step_call_evcar)

# == Lexing, parsing, and writing logic

if b"" == "":  # Python 2
    def _c_char_to_len1(char): return char
    def _c_len1_to_char(len1): return len1
    def _c_char_to_int(char): return ord(char)
    def _c_int_to_char(code): return chr(code)
    def _c_join_chars(chars): return b"".join(chars)
else:  # Python 3+
    def _c_char_to_len1(char): return chr(char)
    def _c_len1_to_char(len1): return ord(len1)
    def _c_char_to_int(char): return char
    def _c_int_to_char(code): return code
    def _c_join_chars(chars): return bytes(chars)
def _c_str_to_bytes(string): return _c_join_chars([_c_len1_to_char(len1) for len1 in string])
def _c_bytes_to_str(bytes_): return "".join([_c_char_to_len1(char) for char in bytes_])

_TOKEN_PATTERN = re.compile(b"|".join([
    br'[()]',  # open and close brackets
    br'[^ \t\r\n();"]+',  # symbol-like tokens
    br'"(?:[^"\\\r\n]|\\[^\r\n])*"',  # single-line strings
    br'[ \t\r]+',  # horizontal whitespace
    br'\n',  # newline (parsed separately to count lines)
    br';[^\r\n]*',  # single-line comments
]))
def tokenize(text, offsets=None, init_line_no=0, init_char_no=0):
    result = []
    i = 0
    len_text = len(text)
    line_no = init_line_no
    line_start_i = -init_char_no
    while i < len_text:
        match = _TOKEN_PATTERN.match(text, i)
        if match is None:
            raise ParsingError("unknown syntax", line_no, i - line_start_i)
        token = match.group()
        if token == b"\n":
            line_no += 1
            line_start_i = i + 1
        elif token[0] not in b" \t\r;":
            result.append(token)
            if offsets is not None:
                offsets.append(line_no)
                offsets.append(i - line_start_i)
        i = match.end()
    return result

_STRING_PATTERN = re.compile(b"|".join([
    br'[^\\]',  # normal characters
    br'\\x[a-fA-F0-9][a-fA-F0-9]',  # hex escape sequence
    br'\\[abtnr"\\]',  # common escape sequences
]))
def parse(tokens, offsets=None, locations=None):
    token = tokens.pop()
    line_no = offsets.pop() if offsets is not None else -1
    char_no = offsets.pop() if offsets is not None else -1
    if token == b")":
        raise ParsingError("unmatched close bracket", line_no, char_no)
    if token == b"(":
        expr, _, _ = _parse_elements(
            tokens,
            offsets=offsets, locations=locations,
            line_no=line_no, char_no=char_no,
            first_line_no=line_no, first_char_no=char_no,
        )
        return expr
    if token == b".":
        raise ParsingError("unexpected dot", line_no, char_no)
    if token == b"#t" or token == b"#T":
        return TRUE
    if token == b"#f" or token == b"#F":
        return FALSE
    if token.lower() == b"#ignore":
        return IGNORE
    if token.lower() == b"#inert":
        return INERT
    if token[0] == b'"'[0]:
        i = 1
        len_token = len(token) - 1
        chars = []
        while i < len_token:
            match = _STRING_PATTERN.match(token, i)
            if match is None:
                raise ParsingError("unknown string escape", line_no, char_no + i)
            part = match.group()
            if part[0] != b"\\"[0]:
                chars.append(part[0])
            elif part[1] == b"x"[0]:
                chars.append(_c_int_to_char(int(part[2:4], 16)))
            else:
                chars.append(b'\a\b\t\n\r"\\'[b'abtnr"\\'.find(part[1])])
            i = match.end()
        return String(_c_join_chars(chars))
    if _c_char_to_len1(token[0]).isdigit() or token[0] in b"+-" and len(token) > 1 and _c_char_to_len1(token[1]).isdigit():
        try:
            return Int(int(token))
        except ValueError:
            raise ParsingError("unknown number", line_no, char_no)
    if token[0] != b"#"[0]:
        symbol = Symbol(token.lower())
        if locations is not None:
            locations.append((symbol, line_no, char_no, line_no, char_no + len(token)))
        return symbol
    raise ParsingError("unknown token", line_no, char_no)

def _parse_elements(
    tokens,
    offsets=None, locations=None,
    line_no=-1, char_no=-1,
    first_line_no=-1, first_char_no=-1,
):
    if not tokens:
        raise ParsingError("unmatched open bracket", first_line_no, first_char_no)
    token = tokens[-1]
    if token == b")":
        tokens.pop()
        end_line_no = offsets.pop() if offsets is not None else -1
        end_char_no = offsets.pop() if offsets is not None else -1
        return NIL, end_line_no, end_char_no
    if token == b".":
        if line_no == first_line_no and char_no == first_char_no:
            line_no = offsets[-1] if offsets is not None else -1
            char_no = offsets[-2] if offsets is not None else -1
            raise ParsingError("missing car element", line_no, char_no)
        tokens.pop()
        if offsets is not None:
            offsets.pop()
            offsets.pop()
        if not tokens:
            raise ParsingError("unmatched open bracket and missing cdr element", first_line_no, first_char_no)
        if tokens[-1] == b")":
            line_no = offsets[-1] if offsets is not None else -1
            char_no = offsets[-2] if offsets is not None else -1
            raise ParsingError("unexpected close bracket", line_no, char_no)
        element = parse(tokens, offsets=offsets, locations=locations)
        if not tokens:
            raise ParsingError("unmatched open bracket", first_line_no, first_char_no)
        end_line_no = offsets.pop() if offsets is not None else -1
        end_char_no = offsets.pop() if offsets is not None else -1
        if tokens.pop() != b")":
            raise ParsingError("expected close bracket", end_line_no, end_char_no)
        return element, end_line_no, end_char_no
    element = parse(tokens, offsets=offsets, locations=locations)
    if not tokens:
        raise ParsingError("unmatched open bracket", first_line_no, first_char_no)
    next_line_no = offsets[-1] if offsets is not None else -1
    next_char_no = offsets[-2] if offsets is not None else -1
    rest, end_line_no, end_char_no = _parse_elements(
        tokens,
        offsets=offsets, locations=locations,
        line_no=next_line_no, char_no=next_char_no,
        first_line_no=first_line_no, first_char_no=first_char_no,
    )
    pair = ImmutablePair(element, rest)
    if locations is not None:
        locations.append((pair, line_no, char_no, end_line_no, end_char_no + 1))
    return pair, end_line_no, end_char_no

# Helper class to handle REPL input state
class _InteractiveParser:
    def __init__(self):
        self.curr_lines = []
        self.curr_tokens = []
        self.curr_offsets = []
        self.curr_exprs = []
        self.curr_locations = []
        self.last_lines = None
    @staticmethod
    @objectmodel.specialize.call_location()
    def extendleft(a, b):
        a.reverse()
        a.extend(b)
        a.reverse()
    def handle(self, line, lines=None, locations=None):  # returns done, exprs
        if lines is None: lines = []
        if locations is None: locations = []
        # Add line to history
        if line and line[-1] == b"\n"[0]:
            self.curr_lines.append(line[:-1])
        else:
            self.curr_lines.append(line)
        try:
            # Try to tokenize the line
            temp_offsets = []
            temp_tokens = tokenize(
                line, offsets=temp_offsets,
                init_line_no=len(lines)+len(self.curr_lines)-1,
                init_char_no=0,
            )
            self.extendleft(self.curr_tokens, temp_tokens)
            self.extendleft(self.curr_offsets, temp_offsets)
            # Try to parse the tokens
            copy_tokens = self.curr_tokens[:]
            copy_offsets = self.curr_offsets[:]
            while copy_tokens:
                assert copy_offsets
                temp_locations = []
                temp_expr = parse(
                    copy_tokens,
                    offsets=copy_offsets,
                    locations=temp_locations,
                )
                self.curr_exprs.append(temp_expr)
                self.curr_locations.extend(temp_locations)
                del self.curr_tokens[len(copy_tokens):]
                del self.curr_offsets[len(copy_offsets):]
        except ParsingError as e:
            if e.message.startswith("unmatched open bracket"):
                # More input is needed
                return False, []
            # Save lines (for later printing) and clear state
            self.last_lines = self.curr_lines[:]
            del self.curr_lines[:]
            del self.curr_tokens[:]
            del self.curr_offsets[:]
            del self.curr_exprs[:]
            del self.curr_locations[:]
            raise
        # All tokens were parsed, return expressions
        lines.extend(self.curr_lines)
        locations.extend(self.curr_locations)
        copy_exprs = self.curr_exprs[:]
        del self.curr_lines[:]
        del self.curr_locations[:]
        del self.curr_exprs[:]
        return True, copy_exprs

def _prompt_lines(stdin, stdout, prompt_list):
    leftover = []
    while True:
        # Output the prompt if at the start of a line
        if not leftover:
            stdout.write(prompt_list[0])
            stdout.flush()
        # Read a chunk of data, usually ends with a newline
        part = stdin.readline()
        if not part:
            if leftover:
                yield "".join(leftover)
            return
        # Split on newlines and yield each line
        i = part.find(b"\n")
        if i < 0:
            leftover.append(part)
        else:
            leftover.append(part[:i+1])
            yield b"".join(leftover)
            del leftover[:]
            while True:
                j = part.find(b"\n", i+1)
                if j < 0:
                    if i+1 < len(part):
                        leftover.append(part[i+1:])
                    break
                else:
                    yield part[i+1:j+1]
                    i = j

def _f_write(file, obj):
    if isinstance(obj, Nil):
        file.write(b"()")
    elif isinstance(obj, Int):
        file.write(b"%d" % (obj.value,))
    elif isinstance(obj, String):
        file.write(b'"')
        for char in obj.value:
            code = _c_char_to_int(char)
            if char in b'\a\b\t\n\r"\\':  # escape sequences
                file.write(b"\\")
                file.write(_c_join_chars([b'abtnr"\\'[b'\a\b\t\n\r"\\'.find(char)]]))
            elif not 32 <= code < 128:  # unprintable codes
                file.write(b"\\x")
                file.write(_c_join_chars([b"0123456789abcdef"[code//16]]))
                file.write(_c_join_chars([b"0123456789abcdef"[code%16]]))
            else:
                file.write(_c_join_chars([char]))
        file.write(b'"')
    elif isinstance(obj, Symbol):
        file.write(obj.name)
    elif isinstance(obj, Ignore):
        file.write(b"#ignore")
    elif isinstance(obj, Inert):
        file.write(b"#inert")
    elif isinstance(obj, Boolean):
        if obj.value:
            file.write(b"#t")
        else:
            file.write(b"#f")
    elif isinstance(obj, Pair):
        file.write(b"(")
        _f_write(file, obj.car)
        obj_cdr = obj.cdr
        while isinstance(obj_cdr, Pair):
            obj = obj_cdr
            file.write(b" ")
            _f_write(file, obj.car)
            obj_cdr = obj.cdr
        if not isinstance(obj_cdr, Nil):
            file.write(b" . ")
            _f_write(file, obj_cdr)
        file.write(b")")
    else:
        file.write(b"#unknown")

def _f_print_trace(file, continuation, sources=None):
    assert isinstance(continuation, Continuation)
    # Output stack trace in reverse order, with recent calls last
    frames = []
    while continuation is not None:
        frames.append(continuation)
        continuation = continuation.parent
    while frames:
        continuation = frames.pop()
        # Skip helper frames (part of argument evaluation)
        if continuation._call_info is None:
            continue
        expr = continuation._call_info
        if expr not in sources:
            # Non-source expressions can be evaluated, usually from eval
            file.write(b"  in unknown\n")
            file.write(b"    ")
            _f_write(file, expr)
            file.write(b"\n")
            continue
        # Get source location of expression
        filename, start_line_no, start_char_no, end_line_no, end_char_no = sources[expr]
        if start_line_no == end_line_no:
            line_info = b"%d" % (start_line_no+1,)
        else:
            line_info = b"%d:%d" % (start_line_no+1, end_line_no+1)
        file.write(b"  in %s at %s [%d:%d]\n" % (filename, line_info, start_char_no+1, end_char_no+1))
        # TODO: output the actual content of the lines the expression is from
        file.write(b"    ")
        _f_write(file, expr)
        file.write(b"\n")

def _f_format_syntax_error(file, error, lines, starts_at=0):
    file.write(b"! --- syntax error ---\n")
    file.write(b"  in <stdin> at %d [%d:]\n" % (error.line_no + 1, error.char_no + 1))
    file.write(b"    ")
    file.write(lines[error.line_no - starts_at])
    file.write(b"\n")
    file.write(b"! syntax-error ")
    _f_write(file, String(_c_str_to_bytes(error.message)))
    file.write(b"\n")

def _f_format_evaluation_error(file, error, lines, locations):
    if error.parent is not None:
        file.write(b"! --- stack trace ---\n")
        sources = {}
        for expr, l1, c1, l2, c2 in locations:
            sources[expr] = (b"<stdin>", l1, c1, l2, c2)
        _f_print_trace(file, error.parent, sources=sources)
    file.write(b"! error ")
    _f_write(file, error.value)
    file.write(b"\n")

# == Primitive combiners

# Pair unpacking helper functions (must specialize on call site since the
# return type differs based on rest=True/False.
@objectmodel.specialize.call_location()
def _unpack1(expr, message, rest=False):
    if not isinstance(expr, Pair): raise RuntimeError(message)
    if rest: return expr.car, expr.cdr
    if not isinstance(expr.cdr, Nil): raise RuntimeError(message)
    return expr.car
@objectmodel.specialize.call_location()
def _unpack2(expr, message, rest=False):
    arg1, expr = _unpack1(expr, message, rest=True)
    arg2, expr = _unpack1(expr, message, rest=True)
    if rest: return arg1, arg2, expr
    if not isinstance(expr, Nil): raise RuntimeError(message)
    return arg1, arg2
@objectmodel.specialize.call_location()
def _unpack3(expr, message, rest=False):
    arg1, expr = _unpack1(expr, message, rest=True)
    arg2, expr = _unpack1(expr, message, rest=True)
    arg3, expr = _unpack1(expr, message, rest=True)
    if rest: return arg1, arg2, arg3, expr
    if not isinstance(expr, Nil): raise RuntimeError(message)
    return arg1, arg2, arg3

# (+ a b)
def _operative_plus(env, expr, parent):
    _ERROR = "expected (+ INT INT)"
    a, b = _unpack2(expr, _ERROR)
    if not isinstance(a, Int): raise RuntimeError(_ERROR)
    if not isinstance(b, Int): raise RuntimeError(_ERROR)
    return f_return(parent, Int(a.value + b.value))

# (* a b)
def _operative_times(env, expr, parent):
    _ERROR = "expected (* INT INT)"
    a, b = _unpack2(expr, _ERROR)
    if not isinstance(a, Int): raise RuntimeError(_ERROR)
    if not isinstance(b, Int): raise RuntimeError(_ERROR)
    return f_return(parent, Int(a.value * b.value))

# (<=? a b)
def _operative_less_equal(env, expr, parent):
    _ERROR = "expected (<=? INT INT)"
    a, b = _unpack2(expr, _ERROR)
    if not isinstance(a, Int): raise RuntimeError(_ERROR)
    if not isinstance(b, Int): raise RuntimeError(_ERROR)
    return f_return(parent, TRUE if a.value <= b.value else FALSE)

# (eq? a b)
def _operative_eq(env, expr, parent):
    _ERROR = "expected (eq? ANY ANY)"
    a, b = _unpack2(expr, _ERROR)
    if False:
        pass
    elif isinstance(a, Nil):
        result = TRUE if isinstance(b, Nil) else FALSE
    elif isinstance(a, Ignore):
        result = TRUE if isinstance(b, Ignore) else FALSE
    elif isinstance(a, Inert):
        result = TRUE if isinstance(b, Inert) else FALSE
    elif isinstance(a, Boolean):
        result = TRUE if isinstance(b, Boolean) and a.value == b.value else FALSE
    elif isinstance(a, Int):
        result = TRUE if isinstance(b, Int) and a.value == b.value else FALSE
    elif isinstance(a, Symbol):
        result = TRUE if isinstance(b, Symbol) and a.name == b.name else FALSE
    elif isinstance(a, String):
        result = TRUE if isinstance(b, String) and a.value == b.value else FALSE
    else:
        result = TRUE if a is b else FALSE
    return f_return(parent, result)

# (pair? expr)
def _operative_pair(env, expr, parent):
    _ERROR = "expected (pair? ANY)"
    pair = _unpack1(expr, _ERROR)
    return f_return(parent, TRUE if isinstance(pair, Pair) else FALSE)

# (cons a b)
def _operative_cons(env, expr, parent):
    _ERROR = "expected (cons ANY ANY)"
    a, b = _unpack2(expr, _ERROR)
    return f_return(parent, MutablePair(a, b))

# (car pair)
def _operative_car(env, expr, parent):
    _ERROR = "expected (car PAIR)"
    pair = _unpack1(expr, _ERROR)
    if not isinstance(pair, Pair): raise RuntimeError(_ERROR)
    return f_return(parent, pair.car)

# (cdr pair)
def _operative_cdr(env, expr, parent):
    _ERROR = "expected (cdr PAIR)"
    pair = _unpack1(expr, _ERROR)
    if not isinstance(pair, Pair): raise RuntimeError(_ERROR)
    return f_return(parent, pair.cdr)

# ($vau (dyn args) expr)
def _operative_vau(env, expr, parent):
    _ERROR = "expected ($vau (PARAM PARAM) ANY)"
    envname_name, body = _unpack2(expr, _ERROR)
    envname, name = _unpack2(envname_name, _ERROR)
    if not isinstance(envname, Symbol) and not isinstance(envname, Ignore): raise RuntimeError(_ERROR)
    if not isinstance(name, Symbol) and not isinstance(name, Ignore): raise RuntimeError(_ERROR)
    immutable_body = _f_copy_immutable(body)
    return f_return(parent, Combiner(0, UserDefinedOperative(env, envname, name, immutable_body)))

# (wrap combiner)
def _operative_wrap(env, expr, parent):
    _ERROR = "expected (wrap COMBINER)"
    combiner = _unpack1(expr, _ERROR)
    if not isinstance(combiner, Combiner): raise RuntimeError(_ERROR)
    return f_return(parent, Combiner(combiner.num_wraps + 1, combiner.operative))

# (unwrap combiner)
def _operative_unwrap(env, expr, parent):
    _ERROR = "expected (unwrap COMBINER)"
    combiner = _unpack1(expr, _ERROR)
    if not isinstance(combiner, Combiner): raise RuntimeError(_ERROR)
    if combiner.num_wraps == 0: raise RuntimeError(_ERROR)
    return f_return(parent, Combiner(combiner.num_wraps - 1, combiner.operative))

# (eval env expr)
def _operative_eval(env, expr, parent):
    _ERROR = "expected (eval ENVIRONMENT ANY)"
    environment, expression = _unpack2(expr, _ERROR)
    if not isinstance(environment, Environment): raise RuntimeError(_ERROR)
    return f_eval(environment, expression, parent)

# ($remote-eval env expr)
def _f_remote_eval(static, value, parent):
    assert isinstance(static, FRemoteEvalEnvironment)
    expression = static.expression
    if not isinstance(value, Environment):
        raise RuntimeError("expected environment argument value")
    if parent is not None:
        parent = Continuation(parent.env, parent.operative, parent.parent)
        parent._call_info = expression
    return f_eval(value, expression, parent)
_F_REMOTE_EVAL = PrimitiveOperative(_f_remote_eval)
def _operative_remote_eval(env, expr, parent):
    _ERROR = "expected ($remote-eval ENVIRONMENT ANY)"
    environment, expression = _unpack2(expr, _ERROR)
    next_env = FRemoteEvalEnvironment(expression)
    next_continuation = Continuation(next_env, _F_REMOTE_EVAL, parent)
    next_continuation._call_info = environment
    return f_eval(env, environment, next_continuation)

# (make-environment [parent])
def _operative_make_environment(env, expr, parent):
    _ERROR = "expected (make-environment [ENVIRONMENT])"
    if isinstance(expr, Nil):
        environment = None
    else:
        environment = _unpack1(expr, _ERROR)
        if not isinstance(environment, Environment): raise RuntimeError(_ERROR)
    return f_return(parent, Environment({}, environment))

# ($define! name value)
def _f_define(static, value, parent):
    assert isinstance(static, FDefineEnvironment)
    env = static.env
    assert isinstance(env, Environment)
    name = static.name
    assert isinstance(name, Symbol) or isinstance(name, Ignore)
    if isinstance(name, Symbol):
        _environment_update(env, name, value)
    return f_return(parent, INERT)
_F_DEFINE = PrimitiveOperative(_f_define)
def _operative_define(env, expr, parent):
    _ERROR = "expected ($define! PARAM ANY)"
    name, value = _unpack2(expr, _ERROR)
    if not isinstance(name, Symbol) and not isinstance(name, Ignore): raise RuntimeError(_ERROR)
    next_env = FDefineEnvironment(env, name)
    next_continuation = Continuation(next_env, _F_DEFINE, parent)
    next_continuation._call_info = value
    return f_eval(env, value, next_continuation)

# ($if cond then orelse)
def _f_if(static, result, parent):
    assert isinstance(static, FIfEnvironment)
    env = static.env
    if not isinstance(result, Boolean):
        raise RuntimeError("expected boolean test value")
    if result.value:
        then = static.then
        return f_eval(env, then, parent)
    else:
        orelse = static.orelse
        return f_eval(env, orelse, parent)
_F_IF = PrimitiveOperative(_f_if)
def _operative_if(env, expr, parent):
    _ERROR = "expected ($if ANY ANY ANY)"
    cond, then, orelse = _unpack3(expr, _ERROR)
    next_env = FIfEnvironment(env, then, orelse)
    next_continuation = Continuation(next_env, _F_IF, parent)
    next_continuation._call_info = cond
    return f_eval(env, cond, next_continuation)

# ($binds? env name)
def _f_binds(static, value, parent):
    assert isinstance(static, FBindsEnvironment)
    name = static.name
    if not isinstance(value, Environment):
        raise RuntimeError("expected environment argument value")
    found = _environment_lookup(value, name)
    if found is None:
        return f_return(parent, FALSE)
    return f_return(parent, TRUE)
_F_BINDS = PrimitiveOperative(_f_binds)
def _operative_binds(env, expr, parent):
    _ERROR = "expected ($binds? ENV SYMBOL)"
    env_expr, name = _unpack2(expr, _ERROR)
    if not isinstance(name, Symbol): raise RuntimeError(_ERROR)
    next_env = FBindsEnvironment(name)
    next_continuation = Continuation(next_env, _F_BINDS, parent)
    next_continuation._call_info = env_expr
    return f_eval(env, env_expr, next_continuation)

def _primitive(num_wraps, func):
    return Combiner(num_wraps, PrimitiveOperative(func))
_DEFAULT_ENV = {
    b"+": _primitive(1, _operative_plus),
    b"*": _primitive(1, _operative_times),
    b"<=?": _primitive(1, _operative_less_equal),
    b"eq?": _primitive(1, _operative_eq),
    b"pair?": _primitive(1, _operative_pair),
    b"cons": _primitive(1, _operative_cons),
    b"car": _primitive(1, _operative_car),
    b"cdr": _primitive(1, _operative_cdr),
    b"$vau": _primitive(0, _operative_vau),
    b"wrap": _primitive(1, _operative_wrap),
    b"unwrap": _primitive(1, _operative_unwrap),
    b"eval": _primitive(1, _operative_eval),
    b"$remote-eval": _primitive(0, _operative_remote_eval),
    b"make-environment": _primitive(1, _operative_make_environment),
    b"$define!": _primitive(0, _operative_define),
    b"$if": _primitive(0, _operative_if),
    b"$binds?": _primitive(0, _operative_binds),
    b"$jit-loop-head": Combiner(0, _F_LOOP_HEAD),
}

# == Entry point

def main(argv):
    import os
    # Configure JIT to allow larger traces
    jit.set_param(None, "trace_limit", 1000000)
    jit.set_param(None, "threshold", 131)
    jit.set_param(None, "trace_eagerness", 50)
    jit.set_param(None, "max_unroll_loops", 15)
    user_config_string = os.environ.get("RFEXPROTO_JIT_CONFIG")
    if user_config_string is not None:
        jit.set_user_param(None, user_config_string)

    # Start REPL if no args and is TTY
    if len(argv) == 1 and os.isatty(0):
        # REPL prompts
        PROMPT_1 = b"rf> "  # default prompt
        PROMPT_2 = b"... "  # multi-line prompt
        prompt_list = [PROMPT_1]
        # Setup standard environment
        env = Environment({}, Environment(_DEFAULT_ENV, None))
        # Parser state
        lines = []
        locations = []
        parser = _InteractiveParser()
        # Read STDIN lines one by one
        stdin, stdout, stderr = rfile.create_stdio()
        for line in _prompt_lines(stdin, stdout, prompt_list):
            # Attempt to lex and parse
            try:
                done, exprs = parser.handle(line, lines=lines, locations=locations)
            except ParsingError as e:
                _f_format_syntax_error(stderr, e, parser.last_lines, starts_at=len(lines))
                prompt_list[0] = PROMPT_1
                continue
            if not done:
                prompt_list[0] = PROMPT_2
                continue
            # Evaluate expressions and write their results
            try:
                for expr in exprs:
                    state = _f_toplevel_eval(env, expr)
                    value = fully_evaluate(state)
                    if not isinstance(value, Inert):
                        _f_write(stdout, value)
                        stdout.write(b"\n")
            except EvaluationError as e:
                _f_format_evaluation_error(stderr, e, lines, locations)
            prompt_list[0] = PROMPT_1
        return 0

    # Read whole STDIN
    stdin, stdout, stderr = rfile.create_stdio()
    parts = []
    while True:
        part = stdin.read(2048)
        if not part: break
        parts.append(part)
    text = b"".join(parts)
    # Lex and parse
    try:
        offsets = []
        tokens = tokenize(text, offsets=offsets)
        tokens.reverse()
        offsets.reverse()
        exprs = []
        locations = []
        while tokens:
            exprs.append(parse(tokens, offsets=offsets, locations=locations))
    except ParsingError as e:
        _f_format_syntax_error(stderr, e, text.split(b"\n"))
        return 1
    # Setup standard environment
    env = Environment({}, Environment(_DEFAULT_ENV, None))
    # Evaluate expressions and write their results
    for expr in exprs:
        state = _f_toplevel_eval(env, expr)
        try:
            value = fully_evaluate(state)
            if not isinstance(value, Inert):
                _f_write(stdout, value)
                stdout.write(b"\n")
        except EvaluationError as e:
            _f_format_evaluation_error(stderr, e, text.split(b"\n"), locations)
            return 1
    return 0

# RPython toolchain
def target(driver, args):
    driver.exe_name = __name__
    if driver.config.translation.jit:
        driver.exe_name += "-jit"
    return main, None
def jitpolicy(driver):
    from rpython.jit.codewriter.policy import JitPolicy
    return JitPolicy()

# Python script
if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
