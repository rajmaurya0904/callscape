# callscape

**Builds a single-file, offline HTML call graph of a Python, JavaScript and Go repository, with click-through from every call site to the function body, for people reading code they did not write.**

"Find references" in an editor gives you one hop at a time and forgets where you
came from. A code-intelligence platform answers the question but wants a server and
an afternoon. callscape parses the repo with tree-sitter, resolves calls by name,
and writes one `.html` file you can open anywhere, mail to a colleague, or diff.

## Real output

Run against the small mixed-language repo in `tests/fixtures/sample`:

```console
$ callscape build tests/fixtures/sample -o callscape.html
callscape: 9 files, 34 symbols, 38 edges (31 of 37 call sites resolved)
wrote callscape.html (38 KB)

$ callscape stats tests/fixtures/sample
files      9 (2 go, 3 javascript, 4 python)
symbols    34 (4 class, 16 function, 11 method, 3 struct)
edges      38 (32 call, 6 type)
call sites 37, 31 resolved to repo code (83%), 2 ambiguous

never called from the repository: 1
  main  (goapp/main.go:24)

call cycles: 2
  is_even <-> is_odd
  App.draw <-> render

$ callscape callees tests/fixtures/sample Engine.run --depth 2
Engine.run  (pkg/core.py:20)
|-- Base.start  (pkg/core.py:7)
|   `-- Base.setup  (pkg/core.py:10)
|-- Engine.step  (pkg/core.py:26)
|   `-- fmt  (pkg/helpers.py:4)
`-- log  (pkg/helpers.py:7)
    `-- fmt  (pkg/helpers.py:4)

$ callscape path tests/fixtures/sample main.py::main pkg/helpers.py::fmt
main  (main.py:5)
  -> Engine.run  (pkg/core.py:20)
  -> Engine.step  (pkg/core.py:26)
  -> fmt  (pkg/helpers.py:4)
3 call(s)
```

An ambiguous name is refused with the ids to choose from, rather than guessed:

```console
$ callscape callers tests/fixtures/sample fmt
callscape: 'fmt' is ambiguous, 2 symbols match. Use one of these ids:
  pkg/helpers.py::fmt  (function, line 4)
  web/util.js::fmt  (function, line 2)
```

## Install

Not on PyPI yet, so install from a clone:

```bash
pip install -e .
```

## Usage

```bash
callscape build path/to/repo -o graph.html --open   # the navigable page
callscape stats path/to/repo                        # counts, hot spots, dead code, cycles
callscape callers path/to/repo SYMBOL --depth 2     # who calls it (SYMBOL: name, Class.method or file::name)
callscape callees path/to/repo SYMBOL               # what it calls
callscape path path/to/repo SRC DST                 # shortest call chain
callscape dot path/to/repo --focus SYMBOL > g.dot   # Graphviz export (also: json)
```

`--lang python,go` limits languages, `--exclude 'tests/*'` skips paths (repeatable),
`--types` follows type references too. In the HTML page, press `/` to search symbols,
click a call to jump to the callee, and use the neighbourhood diagram to walk outward.

## How it works

- Files are discovered by extension, skipping `.git`, `node_modules`, virtualenvs and
  similar directories, then parsed with the tree-sitter grammars for each language.
- Extractors record functions, methods, classes and structs, plus the calls and type
  references inside each body.
- Resolution is by name only: lexical scope, then imports, then the same package, then
  a conservative repo-wide fallback. Calls clearly bound to outside code (`os.getcwd`)
  stay unresolved on purpose.
- The graph answers callers, callees, shortest paths, cycles and never-called symbols.
- `build` embeds the graph and the source of each definition as JSON in one HTML page
  with inline CSS and JavaScript. No server, no network.

## Limitations

- No type inference. `obj.run()` is matched by method name, so calls on values of
  unknown type can be missed or reported as ambiguous (2 in the sample above).
- Dynamic dispatch, `getattr`, reflection, decorators that rewrite calls and callbacks
  passed around as values are not followed.
- Only Python, JavaScript (`.js .mjs .cjs .jsx`) and Go. TypeScript is not parsed.
- Definitions longer than 400 lines are truncated in the page (`--max-body-lines`).
- Only the sample fixture and small repos have been exercised in tests; very large
  repos have not been benchmarked.

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

## Licence

MIT, see [LICENSE](LICENSE).
